"""Framework adapters for Stage 8 security decisions.

Nothing in this module binds a socket.  The application factory may compose these
middleware/dependencies after it has made an explicit local-only or LAN decision.
"""

from __future__ import annotations

import re
import time
from contextlib import suppress
from http import HTTPStatus
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import Cookie, Depends, HTTPException, Request, Response, WebSocket
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from momo.application.services.security_service import IssuedSession, SecurityService
from momo.domain.security import (
    AuditOutcome,
    AuthorizedPrincipal,
    SecuritySurface,
    SecurityViolation,
)

SESSION_COOKIE_NAME = "momo_session"
SAFE_CORS_METHODS = "GET, HEAD, OPTIONS, POST, PUT, PATCH, DELETE"
SAFE_CORS_HEADERS = (
    "Authorization, Content-Type, X-Request-ID, X-MOMO-Backup-SHA256, "
    "X-MOMO-Restore-Confirmation, X-MOMO-Operator-Session"
)
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def get_security_service(request: Request) -> SecurityService:
    return cast(SecurityService, request.app.state.security_service)


SecurityServiceDependency = Annotated[SecurityService, Depends(get_security_service)]
SessionCookie = Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)]


def security_http_error(error: SecurityViolation) -> HTTPException:
    if error.code in {"RATE_LIMITED", "RATE_LIMIT_CAPACITY"}:
        status_code = HTTPStatus.TOO_MANY_REQUESTS
    elif error.code in {"AUTH_REQUIRED", "AUTH_INVALID"}:
        status_code = HTTPStatus.UNAUTHORIZED
    else:
        status_code = HTTPStatus.FORBIDDEN
    return HTTPException(
        status_code=int(status_code),
        detail={"code": error.code, "message": error.message},
    )


def _request_credentials(request: Request, session_cookie: str | None) -> dict[str, Any]:
    return {
        "authorization": request.headers.get("authorization"),
        "session_cookie": session_cookie,
        "query_keys": tuple(request.query_params.keys()),
    }


async def authorize_rest_request(
    request: Request,
    service: SecurityServiceDependency,
    session_cookie: SessionCookie = None,
) -> AuthorizedPrincipal:
    try:
        principal = service.authorize(
            surface=SecuritySurface.REST,
            **_request_credentials(request, session_cookie),
        )
    except SecurityViolation as error:
        raise security_http_error(error) from error
    request.state.security_principal = principal
    return principal


async def authorize_control_request(
    request: Request,
    service: SecurityServiceDependency,
    session_cookie: SessionCookie = None,
) -> AuthorizedPrincipal:
    try:
        principal = service.authorize_control(
            authorization=request.headers.get("authorization"),
            session_cookie=session_cookie,
            query_keys=tuple(request.query_params.keys()),
        )
    except SecurityViolation as error:
        raise security_http_error(error) from error
    request.state.security_principal = principal
    return principal


async def authorize_priority_stop_request(
    request: Request,
    service: SecurityServiceDependency,
    session_cookie: SessionCookie = None,
) -> AuthorizedPrincipal:
    """Authenticate Stop with CONTROL scope without allowing rate limit to block it."""

    try:
        principal = service.authorize(
            surface=SecuritySurface.CONTROL,
            authorization=request.headers.get("authorization"),
            session_cookie=session_cookie,
            query_keys=tuple(request.query_params.keys()),
        )
    except SecurityViolation as error:
        raise security_http_error(error) from error
    request.state.security_principal = principal
    return principal


async def authorize_vision_request(
    request: Request,
    service: SecurityServiceDependency,
    session_cookie: SessionCookie = None,
) -> AuthorizedPrincipal:
    try:
        principal = service.authorize(
            surface=SecuritySurface.VISION,
            **_request_credentials(request, session_cookie),
        )
    except SecurityViolation as error:
        raise security_http_error(error) from error
    request.state.security_principal = principal
    return principal


async def authorize_websocket(
    websocket: WebSocket, service: SecurityService
) -> AuthorizedPrincipal:
    """Authorize before accept; long-term credentials never enter the URL."""

    origin = websocket.headers.get("origin")
    try:
        if not service.policy.allows_origin(origin, required=True):
            raise SecurityViolation("ORIGIN_DENIED", "WebSocket Origin is not allowlisted")
        principal = service.authorize(
            surface=SecuritySurface.WEBSOCKET,
            authorization=websocket.headers.get("authorization"),
            session_cookie=websocket.cookies.get(SESSION_COOKIE_NAME),
            websocket_protocols=websocket.headers.get("sec-websocket-protocol"),
            query_keys=tuple(websocket.query_params.keys()),
        )
    except SecurityViolation as error:
        code = 4401 if error.code in {"AUTH_REQUIRED", "AUTH_INVALID"} else 4403
        await websocket.close(code=code, reason=error.code)
        raise
    websocket.state.security_principal = principal
    return principal


def reauthorize_http_stream(request: Request, surface: SecuritySurface) -> bool:
    """Revalidate an established streaming request before each emitted item."""

    service = get_security_service(request)
    try:
        principal = service.authorize(
            surface=surface,
            **_request_credentials(
                request,
                request.cookies.get(SESSION_COOKIE_NAME),
            ),
        )
    except SecurityViolation:
        return False
    request.state.security_principal = principal
    return True


def set_session_cookie(response: Response, issued: IssuedSession, *, secure: bool) -> None:
    """Deliver a short session without placing it in JSON, a URL, or browser storage."""

    max_age = max(1, int((issued.grant.expires_at - issued.grant.issued_at).total_seconds()))
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=issued.token,
        max_age=max_age,
        path="/api/v1",
        secure=secure,
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/api/v1",
        secure=secure,
        httponly=True,
        samesite="strict",
    )


class BodySizeLimitMiddleware:
    """Fail closed on declared or streamed request bodies above a fixed cap."""

    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        if not 1024 <= max_body_bytes <= 32 * 1024 * 1024:
            raise ValueError("max_body_bytes is outside the supported bound")
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        lengths = [value for key, value in scope.get("headers", ()) if key == b"content-length"]
        if len(lengths) > 1:
            await self._reject(scope, receive, send, "ambiguous Content-Length")
            return
        if lengths:
            try:
                declared = int(lengths[0].decode("ascii"))
            except (UnicodeError, ValueError):
                await self._reject(scope, receive, send, "invalid Content-Length")
                return
            if declared < 0 or declared > self.max_body_bytes:
                await self._reject(scope, receive, send, "request body is too large")
                return

        consumed = 0
        exceeded = False

        async def bounded_receive() -> Message:
            nonlocal consumed, exceeded
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_body_bytes:
                    exceeded = True
                    raise _BodyTooLargeError
            return message

        try:
            await self.app(scope, bounded_receive, send)
        except _BodyTooLargeError:
            if not exceeded:  # pragma: no cover - exception is private to this wrapper
                raise
            await self._send_error(send, "request body is too large")

    async def _reject(self, scope: Scope, receive: Receive, send: Send, message: str) -> None:
        del scope, receive
        await self._send_error(send, message)

    @staticmethod
    async def _send_error(send: Send, message: str) -> None:
        payload = (
            '{"code":"REQUEST_BODY_TOO_LARGE","message":"' + message + '","details":{}}'
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})


class _BodyTooLargeError(BaseException):
    """Bypass application exception handlers so the outer body guard owns the response."""

    pass


class StrictOriginMiddleware:
    """Exact Origin allowlist with no wildcard response path."""

    def __init__(self, app: ASGIApp, *, service: SecurityService) -> None:
        self.app = app
        self.service = service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", ())}
        raw_origin = headers.get(b"origin")
        origin = raw_origin.decode("latin-1") if raw_origin is not None else None
        if origin is not None and not self.service.policy.allows_origin(origin):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 4403, "reason": "ORIGIN_DENIED"})
            else:
                await self._reject_origin(send)
            return
        if scope["type"] == "http" and scope.get("method") == "OPTIONS" and origin is not None:
            await self._preflight(send, origin)
            return

        async def cors_send(message: Message) -> None:
            if message["type"] == "http.response.start" and origin is not None:
                response_headers = list(message.get("headers", ()))
                response_headers.extend(
                    [
                        (b"access-control-allow-origin", origin.encode("latin-1")),
                        (b"access-control-allow-credentials", b"true"),
                        (
                            b"access-control-expose-headers",
                            b"X-MOMO-Backup-SHA256, Content-Disposition",
                        ),
                        (b"vary", b"Origin"),
                    ]
                )
                message = {**message, "headers": response_headers}
            await send(message)

        await self.app(scope, receive, cors_send)

    @staticmethod
    async def _preflight(send: Send, origin: str) -> None:
        headers = [
            (b"access-control-allow-origin", origin.encode("latin-1")),
            (b"access-control-allow-credentials", b"true"),
            (b"access-control-allow-methods", SAFE_CORS_METHODS.encode("ascii")),
            (b"access-control-allow-headers", SAFE_CORS_HEADERS.encode("ascii")),
            (b"access-control-max-age", b"600"),
            (b"vary", b"Origin"),
            (b"content-length", b"0"),
        ]
        await send(
            {"type": "http.response.start", "status": HTTPStatus.NO_CONTENT, "headers": headers}
        )
        await send({"type": "http.response.body", "body": b""})

    @staticmethod
    async def _reject_origin(send: Send) -> None:
        payload = b'{"code":"ORIGIN_DENIED","message":"Origin is not allowlisted","details":{}}'
        await send(
            {
                "type": "http.response.start",
                "status": HTTPStatus.FORBIDDEN,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})


class StructuredRequestAuditMiddleware:
    """Emit one bounded, redacted audit record for every HTTP request."""

    def __init__(self, app: ASGIApp, *, service: SecurityService) -> None:
        self.app = app
        self.service = service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_ids = [
            value.decode("latin-1")
            for key, value in scope.get("headers", ())
            if key.lower() == b"x-request-id"
        ]
        requested_id = request_ids[0] if len(request_ids) == 1 else ""
        request_id = requested_id if _REQUEST_ID_PATTERN.fullmatch(requested_id) else str(uuid4())
        state = cast(dict[str, Any], scope.setdefault("state", {}))
        state["request_id"] = request_id
        status_code = int(HTTPStatus.INTERNAL_SERVER_ERROR)
        started = time.monotonic()

        async def audit_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", ()))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        raised = False
        try:
            await self.app(scope, receive, audit_send)
        except BaseException:
            raised = True
            raise
        finally:
            duration_ms = max(0.0, (time.monotonic() - started) * 1000.0)
            if raised or status_code >= 500:
                outcome = AuditOutcome.FAILED
            elif status_code >= 400:
                outcome = AuditOutcome.REJECTED
            else:
                outcome = AuditOutcome.COMPLETED
            principal = state.get("security_principal")
            principal_id = (
                principal.principal_id if isinstance(principal, AuthorizedPrincipal) else None
            )
            error_code = _state_identifier(state.get("error_code"))
            if error_code is None and status_code >= 400:
                error_code = f"HTTP_{status_code}"
            # An audit volume failure must not turn a completed safety stop into
            # an HTTP failure. The bounded in-memory sink is the safe default.
            with suppress(OSError, TypeError, ValueError):
                self.service.audit(
                    request_id=request_id,
                    command_id=_state_identifier(state.get("command_id")),
                    robot_id=_state_identifier(state.get("robot_id")),
                    principal_id=principal_id,
                    source=(
                        f"HTTP {str(scope.get('method', 'UNKNOWN'))[:16]} "
                        f"{str(scope.get('path', '/'))[:400]}"
                    ),
                    mode=_state_text(state.get("mode")),
                    preflight=_state_text(state.get("preflight")),
                    outcome=outcome,
                    duration_ms=min(duration_ms, 86_400_000.0),
                    error_code=error_code,
                    details={"status_code": status_code},
                )


def _state_identifier(value: object) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    return candidate if _REQUEST_ID_PATTERN.fullmatch(candidate) else None


def _state_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)[:500]


async def read_bounded_body(request: Request, *, maximum_bytes: int) -> bytes:
    """Read a raw upload without trusting Content-Length or accepting a path."""

    if not 1 <= maximum_bytes <= 32 * 1024 * 1024:
        raise ValueError("maximum_bytes is outside the supported bound")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > maximum_bytes:
            raise HTTPException(
                status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                detail={
                    "code": "BACKUP_TOO_LARGE",
                    "message": "Backup upload exceeds the size limit",
                },
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail={"code": "EMPTY_BODY", "message": "Request body is empty"},
        )
    return b"".join(chunks)
