"""Stage 8 local/LAN security decisions without opening sockets."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from starlette.requests import Request as StarletteRequest

from momo.api.app import create_app
from momo.api.routes import ws_robot as ws_robot_route
from momo.api.routes.vision import stream as vision_stream
from momo.api.security import (
    BodySizeLimitMiddleware,
    StrictOriginMiddleware,
    StructuredRequestAuditMiddleware,
)
from momo.application.services.security_service import (
    BoundedJsonlAuditSink,
    BoundedMemoryAuditSink,
    PrincipalRateLimiter,
    SecurityService,
    redact_for_log,
)
from momo.domain.security import (
    AuditOutcome,
    NetworkExposureMode,
    NetworkSecurityPolicy,
    SecuritySurface,
    SecurityViolation,
)
from momo.settings import Settings
from tests.stage3_helpers import FakeClock

STRONG_TOKEN = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"


class MutableSecurityClock:
    def __init__(self) -> None:
        self.wall = datetime(2026, 8, 24, 1, 2, 3, tzinfo=UTC)
        self.monotonic_value = 0.0

    def now(self) -> datetime:
        return self.wall

    def monotonic(self) -> float:
        return self.monotonic_value

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.monotonic_value += seconds


def lan_policy() -> NetworkSecurityPolicy:
    return NetworkSecurityPolicy(
        exposure_mode=NetworkExposureMode.LAN,
        bind_host="192.168.10.5",
        lan_enabled=True,
        allowed_origins=("http://192.168.10.5:5173",),
        require_authentication=True,
    )


def test_localhost_is_default_and_lan_requires_explicit_private_authenticated_policy() -> None:
    default = NetworkSecurityPolicy()
    assert default.bind_host == "127.0.0.1"
    assert default.exposure_mode is NetworkExposureMode.LOCAL_ONLY
    assert default.lan_enabled is False

    with pytest.raises(ValidationError, match="loopback"):
        NetworkSecurityPolicy(bind_host="192.168.1.4")
    with pytest.raises(ValidationError, match="explicit lan_enabled"):
        NetworkSecurityPolicy(
            exposure_mode=NetworkExposureMode.LAN,
            bind_host="192.168.1.4",
            require_authentication=True,
        )
    with pytest.raises(ValidationError, match="concrete private"):
        NetworkSecurityPolicy(
            exposure_mode=NetworkExposureMode.LAN,
            bind_host="0.0.0.0",
            lan_enabled=True,
            require_authentication=True,
        )
    with pytest.raises(ValidationError, match="wildcard"):
        NetworkSecurityPolicy(allowed_origins=("*",))
    with pytest.raises(ValidationError, match="API bind host"):
        NetworkSecurityPolicy(
            exposure_mode=NetworkExposureMode.LAN,
            bind_host="192.168.10.5",
            lan_enabled=True,
            allowed_origins=("http://192.168.10.8:5173",),
            require_authentication=True,
        )
    with pytest.raises(ValidationError, match="HTTP scheme"):
        NetworkSecurityPolicy(
            exposure_mode=NetworkExposureMode.LAN,
            bind_host="192.168.10.5",
            lan_enabled=True,
            allowed_origins=("https://192.168.10.5:5173",),
            require_authentication=True,
        )


def test_lan_auth_stores_only_digest_and_sessions_expire_and_are_scoped() -> None:
    clock = MutableSecurityClock()
    service = SecurityService(
        lan_policy(),
        lan_token=STRONG_TOKEN,
        now=clock.now,
        monotonic=clock.monotonic,
    )
    assert STRONG_TOKEN not in repr(service.__dict__)
    long_term = service.authorize(
        surface=SecuritySurface.REST,
        authorization=f"Bearer {STRONG_TOKEN}",
    )
    assert long_term.authentication == "LONG_TERM_TOKEN"
    with pytest.raises(SecurityViolation, match="invalid"):
        service.authorize(
            surface=SecuritySurface.VISION,
            session_cookie=STRONG_TOKEN,
        )

    issued = service.issue_session(
        authorization=f"Bearer {STRONG_TOKEN}",
        principal_id="operator-a",
        surfaces=(SecuritySurface.VISION, SecuritySurface.WEBSOCKET),
        ttl=timedelta(minutes=2),
    )
    principal = service.authorize(
        surface=SecuritySurface.VISION,
        session_cookie=issued.token,
    )
    assert principal.principal_id == "operator-a"
    with pytest.raises(SecurityViolation, match="not authorized"):
        service.authorize(surface=SecuritySurface.CONTROL, session_cookie=issued.token)
    clock.advance(121)
    with pytest.raises(SecurityViolation, match="invalid"):
        service.authorize(surface=SecuritySurface.VISION, session_cookie=issued.token)


def test_credentials_in_query_are_rejected_even_for_local_mode_and_weak_tokens_fail() -> None:
    clock = MutableSecurityClock()
    local = SecurityService(
        NetworkSecurityPolicy(),
        lan_token=None,
        now=clock.now,
        monotonic=clock.monotonic,
    )
    with pytest.raises(SecurityViolation) as query_error:
        local.authorize(surface=SecuritySurface.REST, query_keys=("access_token",))
    assert query_error.value.code == "QUERY_CREDENTIAL_FORBIDDEN"

    with pytest.raises(SecurityViolation) as token_error:
        SecurityService(
            lan_policy(),
            lan_token="not-random-not-random-not-random",
            now=clock.now,
            monotonic=clock.monotonic,
        )
    assert token_error.value.code == "WEAK_TOKEN"


def test_lan_browser_exchange_uses_httponly_cookie_without_returning_a_token() -> None:
    ui_origin = "http://192.168.10.5:5173"
    settings = Settings(
        server_host="192.168.10.5",
        lan_enabled=True,
        lan_auth_token=SecretStr(STRONG_TOKEN),
        lan_allowed_origins=(ui_origin,),
    )
    with TestClient(create_app(settings=settings), base_url="http://192.168.10.5") as client:
        issued = client.post(
            "/api/v1/security/session",
            headers={
                "Origin": ui_origin,
                "Authorization": f"Bearer {STRONG_TOKEN}",
            },
        )
        assert issued.status_code == 200
        assert "session_token" not in issued.json()
        assert issued.json()["surfaces"] == ["CONTROL", "REST", "VISION", "WEBSOCKET"]
        cookie = issued.headers["set-cookie"]
        assert "momo_session=" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie
        assert "Path=/api/v1" in cookie
        assert "Max-Age=1800" in cookie
        assert "expires=" in cookie.lower()
        assert "Secure" not in cookie

        authenticated = client.get("/api/v1/health", headers={"Origin": ui_origin})
        assert authenticated.status_code == 200

        revoked = client.delete(
            "/api/v1/security/session",
            headers={"Origin": ui_origin},
        )
        assert revoked.status_code == 204
        assert "momo_session=" in revoked.headers["set-cookie"]
        denied = client.get("/api/v1/health", headers={"Origin": ui_origin})
        assert denied.status_code == 401


def test_browser_cookie_ttl_is_independent_from_short_hardware_operator_ttl() -> None:
    ui_origin = "http://192.168.10.5:5173"
    settings = Settings(
        server_host="192.168.10.5",
        lan_enabled=True,
        lan_auth_token=SecretStr(STRONG_TOKEN),
        lan_allowed_origins=(ui_origin,),
        operator_session_ttl_s=30,
        browser_security_session_ttl_s=3600,
    )
    app = create_app(settings=settings)
    assert app.state.device_diagnostics_service.sessions.ttl_s == 30.0

    with TestClient(app, base_url="https://192.168.10.5") as client:
        issued = client.post(
            "/api/v1/security/session",
            headers={
                "Origin": ui_origin,
                "Authorization": f"Bearer {STRONG_TOKEN}",
            },
        )
        assert issued.status_code == 200, issued.text
        payload = issued.json()
        issued_at = datetime.fromisoformat(payload["issued_at"])
        expires_at = datetime.fromisoformat(payload["expires_at"])
        assert expires_at - issued_at == timedelta(seconds=3600)
        cookie = issued.headers["set-cookie"]
        assert "Max-Age=3600" in cookie
        assert "expires=" in cookie.lower()
        assert "Secure" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie


def test_lan_bearer_exchange_replaces_stale_cookie_after_backend_restart() -> None:
    ui_origin = "http://192.168.10.5:5173"
    settings = Settings(
        server_host="192.168.10.5",
        lan_enabled=True,
        lan_auth_token=SecretStr(STRONG_TOKEN),
        lan_allowed_origins=(ui_origin,),
    )
    with TestClient(create_app(settings=settings), base_url="http://192.168.10.5") as first:
        issued = first.post(
            "/api/v1/security/session",
            headers={"Origin": ui_origin, "Authorization": f"Bearer {STRONG_TOKEN}"},
        )
        assert issued.status_code == 200
        stale_cookie = first.cookies.get("momo_session")
        assert stale_cookie

    # A fresh application has intentionally forgotten every old server-side grant,
    # while a real browser still sends the unexpired HttpOnly cookie.
    with TestClient(create_app(settings=settings), base_url="http://192.168.10.5") as restarted:
        restarted.cookies.set(
            "momo_session",
            stale_cookie,
            domain="192.168.10.5",
            path="/api/v1",
        )
        replacement = restarted.post(
            "/api/v1/security/session",
            headers={"Origin": ui_origin, "Authorization": f"Bearer {STRONG_TOKEN}"},
        )
        assert replacement.status_code == 200, replacement.text
        replacement_cookie = restarted.cookies.get(
            "momo_session",
            domain="192.168.10.5",
            path="/api/v1",
        )
        assert replacement_cookie
        assert replacement_cookie != stale_cookie
        assert (
            restarted.get(
                "/api/v1/health",
                headers={"Origin": ui_origin},
            ).status_code
            == 200
        )


@pytest.mark.parametrize("termination", ["expire", "revoke"])
def test_established_websocket_revalidates_expiry_and_revocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    termination: str,
) -> None:
    clock = FakeClock()
    security = SecurityService(
        lan_policy(),
        lan_token=STRONG_TOKEN,
        now=clock.now,
        monotonic=clock.monotonic,
    )
    issued = security.issue_session(
        authorization=f"Bearer {STRONG_TOKEN}",
        principal_id="operator",
        surfaces=(SecuritySurface.WEBSOCKET,),
        ttl=timedelta(seconds=30),
    )

    class RecordingWebSocket:
        def __init__(self, app: FastAPI, cookie: str) -> None:
            self.app = app
            self.headers = {"origin": "http://192.168.10.5:5173"}
            self.cookies = {"momo_session": cookie}
            self.query_params: dict[str, str] = {}
            self.state = SimpleNamespace()
            self.accepted = False
            self.payloads: list[dict[str, object]] = []
            self.closes: list[tuple[int, str]] = []

        async def accept(self) -> None:
            self.accepted = True

        async def send_json(self, payload: dict[str, object]) -> None:
            self.payloads.append(payload)
            if len(self.payloads) == 1:
                if termination == "expire":
                    clock.elapse(31)
                else:
                    security.revoke_session(issued.token)

        async def close(self, *, code: int, reason: str) -> None:
            self.closes.append((code, reason))

    async def scenario() -> None:
        app = create_app(
            Settings(
                runtime_state_directory=str(tmp_path / "runtime"),
                calibration_directory=str(tmp_path / "calibration"),
                pose_directory=str(tmp_path / "poses"),
                motion_library_directory=str(tmp_path / "motions"),
                motion_draft_directory=str(tmp_path / "drafts"),
            )
        )
        app.state.security_service = security
        socket = RecordingWebSocket(app, issued.token)

        async def no_delay() -> None:
            return None

        monkeypatch.setattr(ws_robot_route, "_wait_for_next_publish", no_delay)
        try:
            await ws_robot_route.robot_state_socket(cast(WebSocket, socket))
            assert socket.accepted is True
            assert len(socket.payloads) == 1
            assert socket.closes == [(4401, "AUTH_INVALID")]
        finally:
            await app.state.vision_service.shutdown()
            await app.state.motion_service.shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize("termination", ["expire", "revoke"])
def test_established_vision_stream_revalidates_expiry_and_revocation(
    tmp_path: Path,
    termination: str,
) -> None:
    async def scenario() -> None:
        app = create_app(
            Settings(
                runtime_state_directory=str(tmp_path / "runtime"),
                calibration_directory=str(tmp_path / "calibration"),
                pose_directory=str(tmp_path / "poses"),
                motion_library_directory=str(tmp_path / "motions"),
                motion_draft_directory=str(tmp_path / "drafts"),
            )
        )
        clock = FakeClock()
        security = SecurityService(
            lan_policy(),
            lan_token=STRONG_TOKEN,
            now=clock.now,
            monotonic=clock.monotonic,
        )
        issued = security.issue_session(
            authorization=f"Bearer {STRONG_TOKEN}",
            principal_id="operator",
            surfaces=(SecuritySurface.VISION,),
            ttl=timedelta(seconds=30),
        )
        app.state.security_service = security
        scope: dict[str, Any] = {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/vision/stream",
            "raw_path": b"/api/v1/vision/stream",
            "query_string": b"",
            "headers": [(b"cookie", f"momo_session={issued.token}".encode("ascii"))],
            "client": ("192.168.10.8", 12345),
            "server": ("192.168.10.5", 8000),
            "root_path": "",
            "app": app,
        }
        request = StarletteRequest(scope)
        response = await vision_stream(request, app.state.vision_service)
        iterator = cast(AsyncGenerator[bytes, None], response.body_iterator.__aiter__())
        try:
            first = await anext(iterator)
            assert b"X-Frame-Id" in first
            if termination == "expire":
                clock.elapse(31)
            else:
                security.revoke_session(issued.token)
            with pytest.raises(StopAsyncIteration):
                await anext(iterator)
            for _ in range(20):
                if app.state.vision_service.active_streams == 0:
                    break
                await asyncio.sleep(0)
            assert app.state.vision_service.active_streams == 0
        finally:
            await iterator.aclose()
            await app.state.vision_service.shutdown()
            await app.state.motion_service.shutdown()

    asyncio.run(scenario())


def test_rate_limit_is_per_principal_and_principal_table_is_bounded() -> None:
    clock = MutableSecurityClock()
    limiter = PrincipalRateLimiter(
        limit=2,
        window_seconds=1,
        max_principals=2,
        monotonic=clock.monotonic,
    )
    limiter.consume("a")
    limiter.consume("a")
    with pytest.raises(SecurityViolation) as limited:
        limiter.consume("a")
    assert limited.value.code == "RATE_LIMITED"
    limiter.consume("b")
    with pytest.raises(SecurityViolation) as capacity:
        limiter.consume("c")
    assert capacity.value.code == "RATE_LIMIT_CAPACITY"
    assert limiter.principal_count == 2
    clock.advance(2)
    limiter.consume("c")
    assert limiter.principal_count == 1


def test_control_keepalives_have_a_separate_bounded_rate_budget() -> None:
    clock = MutableSecurityClock()
    service = SecurityService(
        NetworkSecurityPolicy(allowed_origins=("http://127.0.0.1:5173",)),
        lan_token=None,
        now=clock.now,
        monotonic=clock.monotonic,
        control_rate_limit=2,
        control_keepalive_rate_limit=3,
        control_rate_window_seconds=60,
    )
    credentials = {"query_keys": ()}

    service.authorize_control(**credentials)
    service.authorize_control_keepalive(**credentials)
    service.authorize_control_keepalive(**credentials)
    service.authorize_control_keepalive(**credentials)
    # Keepalives did not consume the remaining operator-command slot.
    service.authorize_control(**credentials)

    with pytest.raises(SecurityViolation) as control_limited:
        service.authorize_control(**credentials)
    assert control_limited.value.code == "RATE_LIMITED"
    with pytest.raises(SecurityViolation) as keepalive_limited:
        service.authorize_control_keepalive(**credentials)
    assert keepalive_limited.value.code == "RATE_LIMITED"


def test_strict_origin_echoes_only_allowlisted_origin_and_body_guard_is_bounded() -> None:
    clock = MutableSecurityClock()
    audit_sink = BoundedMemoryAuditSink()
    policy = NetworkSecurityPolicy(
        allowed_origins=("http://127.0.0.1:5173",),
    )
    service = SecurityService(
        policy,
        lan_token=None,
        now=clock.now,
        monotonic=clock.monotonic,
        audit_sink=audit_sink,
    )
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=1024)
    app.add_middleware(StrictOriginMiddleware, service=service)
    app.add_middleware(StructuredRequestAuditMiddleware, service=service)

    @app.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/body")
    async def body(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    with TestClient(app) as client:
        allowed = client.get(
            "/ok",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "X-Request-ID": "client-request-1",
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers["x-request-id"] == "client-request-1"
        assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
        assert allowed.headers["access-control-allow-origin"] != "*"

        denied = client.get("/ok", headers={"Origin": "http://evil.example"})
        assert denied.status_code == 403
        assert denied.json()["code"] == "ORIGIN_DENIED"
        assert "access-control-allow-origin" not in denied.headers

        preflight = client.options(
            "/ok",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": (
                    "X-MOMO-Operator-Session, X-Adversarial-Servo-Command"
                ),
            },
        )
        assert preflight.status_code == 204
        assert preflight.headers["access-control-allow-origin"] != "*"
        allowed_headers = preflight.headers["access-control-allow-headers"].split(", ")
        assert "X-MOMO-Operator-Session" in allowed_headers
        assert "X-Adversarial-Servo-Command" not in allowed_headers
        assert preflight.headers["access-control-allow-methods"] != "*"

        oversized = client.post("/body", content=b"x" * 1025)
        assert oversized.status_code == 413
        assert oversized.json()["code"] == "REQUEST_BODY_TOO_LARGE"
    assert len(audit_sink.events) == 4
    assert audit_sink.events[0].request_id == "client-request-1"
    assert audit_sink.events[-1].error_code == "HTTP_413"


def test_motion_request_populates_structured_audit_context(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            runtime_state_directory=str(tmp_path / "runtime"),
            calibration_directory=str(tmp_path / "calibration"),
            pose_directory=str(tmp_path / "poses"),
            motion_library_directory=str(tmp_path / "motions"),
            motion_draft_directory=str(tmp_path / "drafts"),
        )
    )
    audit_sink = BoundedMemoryAuditSink()
    app.state.security_service.audit_sink = audit_sink

    with TestClient(app) as client:
        connected = client.post("/api/v1/robot/connect")
        assert connected.status_code == 200
        status_payload = connected.json()["status"]
        fk_response = client.get("/api/v1/robot/fk")
        assert fk_response.status_code == 200
        fk_payload = fk_response.json()
        target = dict(status_payload["positions"])
        target["j11"] += 1.0
        accepted = client.post(
            "/api/v1/motion/joints",
            json={
                "expected_state_sequence": status_payload["state_sequence"],
                "expected_profile_fingerprint": status_payload["profile_fingerprint"],
                "expected_kinematics_fingerprint": fk_payload["kinematics_fingerprint"],
                "source": "CONTROL",
                "idempotency_key": "stage8-audit-motion",
                "speed_scale": 1.0,
                "joint_state": {
                    "positions": target,
                    "units": status_payload["units"],
                },
                "duration_s": 1.0,
            },
        )
        assert accepted.status_code == 202, accepted.text
        command_id = accepted.json()["command_id"]

        event = next(item for item in audit_sink.events if item.command_id == command_id)
        assert event.robot_id == "primary"
        assert event.mode == "DRY_RUN"
        assert event.preflight == "ACCEPTED"
        assert event.outcome is AuditOutcome.COMPLETED
        assert event.error_code is None

        invalid = client.post("/api/v1/motion/joints", json={})
        assert invalid.status_code == 422
        assert audit_sink.events[-1].error_code == "REQUEST_VALIDATION_ERROR"


def test_redaction_and_bounded_structured_audit_never_emit_sensitive_values(
    tmp_path: Path,
) -> None:
    raw_token = "raw-secret-token-value"
    quoted_secret = "abcdefghijklmnopabcdefghijklmnop"
    basic_secret = "YWJjZGVmZ2hpamtsbW5vcA=="
    redacted = redact_for_log(
        {
            "authorization": f"Bearer {raw_token}",
            "api_key": quoted_secret,
            "x-api-key": quoted_secret,
            "apikey": quoted_secret,
            "access_key": quoted_secret,
            "private_key": quoted_secret,
            "session_id": "session-value",
            "runtime_path": "/Users/operator/private/runtime.json",
            "serial_port": "/dev/cu.usbserial-ABCD",
            "message": (
                "fault at /srv/momo/runtime.db, /dev/serial/by-id/usb-secret, "
                "and /mnt/custom/private.bin; failure path:/srv/momo/secret.db; "
                r"file:///Users/operator/token.txt; path:C:\Users\operator\secret.db; "
                f"token='{quoted_secret}'; token=\"{quoted_secret}\"; "
                f'{{"token":"{quoted_secret}"}}; api_key: \'{quoted_secret}\'; '
                f"password=`{quoted_secret}`; client_secret={quoted_secret}; "
                f"db.password={quoted_secret}; github-token={quoted_secret}; "
                f"oauth_access_token={quoted_secret}; clientSecret={quoted_secret}; "
                f"Authorization: Basic {basic_secret}"
            ),
        }
    )
    rendered = repr(redacted)
    assert raw_token not in rendered
    assert quoted_secret not in rendered
    assert basic_secret not in rendered
    assert "session-value" not in rendered
    assert "/Users/operator" not in rendered
    assert "/dev/cu.usbserial" not in rendered
    assert "/srv/momo" not in rendered
    assert "/dev/serial/by-id" not in rendered
    assert "/mnt/custom" not in rendered
    assert "path:/srv" not in rendered
    assert "file:///Users" not in rendered
    assert r"C:\Users" not in rendered
    assert "ABCD" in rendered

    clock = MutableSecurityClock()
    memory_sink = BoundedMemoryAuditSink(capacity=2)
    service = SecurityService(
        NetworkSecurityPolicy(),
        lan_token=None,
        now=clock.now,
        monotonic=clock.monotonic,
        audit_sink=memory_sink,
    )
    event = service.audit(
        request_id="request-1",
        command_id="command-1",
        robot_id="primary",
        principal_id="operator",
        source="REST",
        mode="DRY_RUN",
        preflight="accepted",
        outcome=AuditOutcome.COMPLETED,
        duration_ms=12.5,
        details={"token": raw_token, "path": "/Users/operator/config.yaml"},
    )
    assert event.request_id == "request-1"
    assert event.duration_ms == 12.5
    assert len(memory_sink.events) == 1

    hostile_source = service.audit(
        request_id="request-hostile-source",
        source="HTTP GET /api/v1/token:abcdefghijklmnop",
        outcome=AuditOutcome.REJECTED,
        duration_ms=1,
    )
    assert "abcdefghijklmnop" not in hostile_source.source
    memory_rendered = repr(memory_sink.events[0].model_dump(mode="json"))
    assert raw_token not in memory_rendered
    assert "/Users/operator" not in memory_rendered

    jsonl_sink = BoundedJsonlAuditSink(tmp_path / "audit", max_bytes=4096, backup_count=2)
    file_service = SecurityService(
        NetworkSecurityPolicy(),
        lan_token=None,
        now=clock.now,
        monotonic=clock.monotonic,
        audit_sink=jsonl_sink,
    )
    for index in range(12):
        file_service.audit(
            request_id=f"request-{index}",
            source="REST",
            outcome=AuditOutcome.COMPLETED,
            duration_ms=1.0,
            details={
                "token": raw_token,
                "path": "/Users/operator/config.yaml",
                "padding": "x" * 1800,
            },
        )
    files = tuple((tmp_path / "audit").glob("security-audit.jsonl*"))
    assert 1 <= len(files) <= 3
    assert all(path.stat().st_size <= 4096 for path in files)
    audit_text = "".join(path.read_text(encoding="utf-8") for path in files)
    assert raw_token not in audit_text
    assert "/Users/operator" not in audit_text
