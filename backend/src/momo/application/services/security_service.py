"""Credential verification, bounded sessions/rate limits, and log redaction."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import stat
import threading
from collections import deque
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from momo.domain.security import (
    MAX_RATE_LIMIT_PRINCIPALS,
    MAX_SECURITY_SESSIONS,
    AuditOutcome,
    AuthorizedPrincipal,
    NetworkExposureMode,
    NetworkSecurityPolicy,
    SecurityAuditEvent,
    SecuritySurface,
    SecurityViolation,
    SessionGrant,
)

_SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|password|secret|session|token|credential|apikey|"
    r"(?:api|access|private|secret)[_-]?key)",
    re.IGNORECASE,
)
_SERIAL_KEY = re.compile(r"(?:serial|port|device)", re.IGNORECASE)
_PATH_KEY = re.compile(r"(?:path|directory|filename)", re.IGNORECASE)
_SERIAL_VALUE = re.compile(r"(?:/dev/(?:cu|tty)\.[A-Za-z0-9_.-]+|\bCOM\d+\b)", re.IGNORECASE)
_HTTP_URL = re.compile(r"https?://[^\s,;\"']+", re.IGNORECASE)
_FILE_URI = re.compile(r"file://[^\s,;\"']+", re.IGNORECASE)
_UNIX_PATH = re.compile(r"(?<![A-Za-z0-9/])/(?:[^\s,;\"']+)")
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s,;\"']+")
_INLINE_CREDENTIAL = re.compile(
    r"(?<![A-Za-z0-9_])[\"'`]?(?:[A-Za-z][A-Za-z0-9_.-]{0,63})?"
    r"(?:access[_-]?token|authorization|cookie|credential|"
    r"password|refresh[_-]?token|session[_-]?token|secret|token|api[_-]?key|"
    r"access[_-]?key|private[_-]?key|secret[_-]?key)[\"'`]?\s*(?:=|:)\s*"
    r"(?:(?:Bearer|Basic)\s+)?(?:\"[^\"\r\n]{8,}\"|'[^'\r\n]{8,}'|"
    r"`[^`\r\n]{8,}`|[^\s,;}\]]{16,})",
    re.IGNORECASE,
)
_AUTH_CREDENTIAL = re.compile(
    r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/-]{16,}={0,2}",
    re.IGNORECASE,
)
_QUERY_CREDENTIAL_KEYS = frozenset(
    {"token", "access_token", "auth", "authorization", "session", "session_token"}
)
ALL_SURFACES = frozenset(SecuritySurface)


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """One-time session material. Never serialize or log this object."""

    token: str
    grant: SessionGrant


@dataclass(frozen=True, slots=True)
class _StoredSession:
    digest: bytes
    grant: SessionGrant


class SecurityAuditSink(Protocol):
    """Bounded destination for already-redacted structured events."""

    def emit(self, event: SecurityAuditEvent) -> None: ...


class BoundedMemoryAuditSink:
    """Safe default: bounded process-local evidence with no filesystem path."""

    def __init__(self, capacity: int = 1000) -> None:
        if not 1 <= capacity <= 100_000:
            raise ValueError("audit capacity is outside the supported bound")
        self._events: deque[SecurityAuditEvent] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, event: SecurityAuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    @property
    def events(self) -> tuple[SecurityAuditEvent, ...]:
        with self._lock:
            return tuple(self._events)


class BoundedJsonlAuditSink:
    """Fixed-name, size-rotated JSONL with private permissions and no symlink follow."""

    def __init__(
        self,
        directory: Path,
        *,
        max_bytes: int = 2 * 1024 * 1024,
        backup_count: int = 3,
    ) -> None:
        if not 4096 <= max_bytes <= 64 * 1024 * 1024:
            raise ValueError("audit max_bytes is outside the supported bound")
        if not 1 <= backup_count <= 10:
            raise ValueError("audit backup_count is outside the supported bound")
        self._directory = directory.resolve()
        self._destination = self._directory / "security-audit.jsonl"
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._lock = threading.Lock()

    def emit(self, event: SecurityAuditEvent) -> None:
        value = redact_for_log(event.model_dump(mode="json"))
        payload = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        if len(payload) > min(64 * 1024, self._max_bytes):
            compact = event.model_copy(update={"details": {"truncated": True}})
            payload = (
                json.dumps(compact.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
                + "\n"
            ).encode("utf-8")
        with self._lock:
            self._ensure_directory()
            current_size = self._regular_size(self._destination)
            if current_size > self._max_bytes:
                self._destination.unlink()
                current_size = 0
            elif current_size + len(payload) > self._max_bytes:
                self._rotate()
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self._destination, flags, 0o600)
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise OSError("audit destination is not a regular file")
                remaining = memoryview(payload)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:  # pragma: no cover - regular file writes make progress
                        raise OSError("audit write made no progress")
                    remaining = remaining[written:]
                os.fsync(descriptor)
                os.fchmod(descriptor, 0o600)
            finally:
                os.close(descriptor)

    def _ensure_directory(self) -> None:
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = self._directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError("audit directory is not a directory")
        os.chmod(self._directory, 0o700)

    @staticmethod
    def _regular_size(path: Path) -> int:
        if not os.path.lexists(path):
            return 0
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("audit destination is not a regular file")
        return metadata.st_size

    def _rotate(self) -> None:
        oldest = self._destination.with_name(f"{self._destination.name}.{self._backup_count}")
        if os.path.lexists(oldest):
            oldest.unlink()
        for index in range(self._backup_count - 1, 0, -1):
            source = self._destination.with_name(f"{self._destination.name}.{index}")
            destination = self._destination.with_name(f"{self._destination.name}.{index + 1}")
            if os.path.lexists(source):
                os.replace(source, destination)
        if os.path.lexists(self._destination):
            os.replace(
                self._destination, self._destination.with_name(f"{self._destination.name}.1")
            )


def generate_lan_token() -> str:
    """Generate at least 256 bits of URL-safe random token material."""

    return secrets.token_urlsafe(32)


def _require_strong_token(token: str) -> None:
    encoded = token.encode("utf-8")
    if len(encoded) < 32 or len(token) > 512:
        raise SecurityViolation("WEAK_TOKEN", "LAN token must contain at least 32 bytes")
    if len(set(encoded)) < 12:
        raise SecurityViolation("WEAK_TOKEN", "LAN token does not have enough variation")
    probabilities = [encoded.count(value) / len(encoded) for value in set(encoded)]
    entropy = -sum(probability * math.log2(probability) for probability in probabilities)
    if entropy * len(encoded) < 160:
        raise SecurityViolation("WEAK_TOKEN", "LAN token entropy is too low")


def _mask_serial(value: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9]", "", value)[-4:]
    return f"<serial:…{suffix}>" if suffix else "<serial:redacted>"


def redact_text(value: str) -> str:
    """Remove device-local absolute paths and partially mask serial identifiers."""

    masked = _SERIAL_VALUE.sub(lambda match: _mask_serial(match.group(0)), value)
    masked = _HTTP_URL.sub("<redacted-url>", masked)
    masked = _FILE_URI.sub("<redacted-path>", masked)
    masked = _INLINE_CREDENTIAL.sub("<redacted-credential>", masked)
    masked = _AUTH_CREDENTIAL.sub("<redacted-credential>", masked)
    masked = _WINDOWS_PATH.sub("<redacted-path>", masked)
    return _UNIX_PATH.sub("<redacted-path>", masked)


def redact_for_log(value: object, *, _depth: int = 0) -> object:
    """Recursively redact a bounded value before structured logging."""

    if _depth > 8:
        return "<redacted-depth>"
    if isinstance(value, str):
        return redact_text(value[:4000])
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for index, (raw_key, item) in enumerate(value.items()):
            if index >= 128:
                redacted["<truncated>"] = True
                break
            key = redact_text(str(raw_key)[:200])
            if _SENSITIVE_KEY.search(key):
                redacted[key] = "<redacted>"
            elif _SERIAL_KEY.search(key) and isinstance(item, str):
                redacted[key] = _mask_serial(item)
            elif _PATH_KEY.search(key) and isinstance(item, str):
                redacted[key] = "<redacted-path>"
            else:
                redacted[key] = redact_for_log(item, _depth=_depth + 1)
        return redacted
    if isinstance(value, Collection) and not isinstance(value, bytes | bytearray):
        return [redact_for_log(item, _depth=_depth + 1) for item in list(value)[:128]]
    return redact_text(str(value)[:1000])


class PrincipalRateLimiter:
    """Bounded fixed-window limiter that cannot grow with attacker principals."""

    def __init__(
        self,
        *,
        limit: int = 20,
        window_seconds: float = 1.0,
        max_principals: int = MAX_RATE_LIMIT_PRINCIPALS,
        monotonic: Callable[[], float],
    ) -> None:
        if limit < 1 or not 0.1 <= window_seconds <= 3600 or max_principals < 1:
            raise ValueError("rate limit configuration is invalid")
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_principals = max_principals
        self._monotonic = monotonic
        self._events: dict[str, deque[float]] = {}

    def consume(self, principal_id: str) -> None:
        now = self._monotonic()
        cutoff = now - self.window_seconds
        events = self._events.get(principal_id)
        if events is None:
            self._prune_empty(cutoff)
            if len(self._events) >= self.max_principals:
                raise SecurityViolation("RATE_LIMIT_CAPACITY", "Rate limiter is at capacity")
            events = deque(maxlen=self.limit)
            self._events[principal_id] = events
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= self.limit:
            raise SecurityViolation("RATE_LIMITED", "Control request rate limit exceeded")
        events.append(now)

    def _prune_empty(self, cutoff: float) -> None:
        expired = [
            key for key, values in self._events.items() if not values or values[-1] <= cutoff
        ]
        for key in expired:
            del self._events[key]

    @property
    def principal_count(self) -> int:
        return len(self._events)


class SecurityService:
    """In-memory verifier; only keyed digests survive after construction."""

    def __init__(
        self,
        policy: NetworkSecurityPolicy,
        *,
        lan_token: str | None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float],
        max_sessions: int = MAX_SECURITY_SESSIONS,
        control_rate_limit: int = 20,
        control_rate_window_seconds: float = 1.0,
        max_rate_limit_principals: int = MAX_RATE_LIMIT_PRINCIPALS,
        audit_sink: SecurityAuditSink | None = None,
    ) -> None:
        if max_sessions < 1 or max_sessions > MAX_SECURITY_SESSIONS:
            raise ValueError("max_sessions is outside the supported bound")
        if policy.exposure_mode is NetworkExposureMode.LAN and lan_token is None:
            raise SecurityViolation("TOKEN_REQUIRED", "LAN exposure requires a strong token")
        if lan_token is not None:
            _require_strong_token(lan_token)
        self.policy = policy
        self._pepper = secrets.token_bytes(32)
        self._lan_digest = self._digest(lan_token) if lan_token is not None else None
        self._now = now
        self._max_sessions = max_sessions
        self._sessions: dict[bytes, _StoredSession] = {}
        self.control_rate_limiter = PrincipalRateLimiter(
            limit=control_rate_limit,
            window_seconds=control_rate_window_seconds,
            max_principals=max_rate_limit_principals,
            monotonic=monotonic,
        )
        self.audit_sink = audit_sink or BoundedMemoryAuditSink()

    def _digest(self, token: str) -> bytes:
        return hmac.digest(self._pepper, token.encode("utf-8"), hashlib.sha256)

    @staticmethod
    def reject_query_credentials(query_keys: Collection[str]) -> None:
        if {key.casefold() for key in query_keys} & _QUERY_CREDENTIAL_KEYS:
            raise SecurityViolation(
                "QUERY_CREDENTIAL_FORBIDDEN",
                "Credentials must not be supplied in a URL query",
            )

    def authorize(
        self,
        *,
        surface: SecuritySurface,
        authorization: str | None = None,
        session_cookie: str | None = None,
        websocket_protocols: str | None = None,
        query_keys: Collection[str] = (),
    ) -> AuthorizedPrincipal:
        self.reject_query_credentials(query_keys)
        if not self.policy.require_authentication:
            return AuthorizedPrincipal(
                principal_id="local-operator",
                authentication="LOCAL",
                surfaces=ALL_SURFACES,
            )
        credential = self._credential_token(
            authorization=authorization,
            session_cookie=session_cookie,
            websocket_protocols=websocket_protocols,
        )
        if credential is None:
            raise SecurityViolation("AUTH_REQUIRED", "Authentication is required")
        token, long_term_transport = credential
        digest = self._digest(token)
        if (
            long_term_transport
            and self._lan_digest is not None
            and hmac.compare_digest(digest, self._lan_digest)
        ):
            return AuthorizedPrincipal(
                principal_id="lan-operator",
                authentication="LONG_TERM_TOKEN",
                surfaces=ALL_SURFACES,
            )
        self._prune_sessions()
        stored = self._sessions.get(digest)
        if stored is None or not hmac.compare_digest(digest, stored.digest):
            raise SecurityViolation("AUTH_INVALID", "Authentication is invalid")
        if surface not in stored.grant.surfaces:
            raise SecurityViolation("AUTH_SCOPE_DENIED", "Session is not authorized for this API")
        return AuthorizedPrincipal(
            principal_id=stored.grant.principal_id,
            authentication="SESSION",
            surfaces=stored.grant.surfaces,
            expires_at=stored.grant.expires_at,
        )

    @staticmethod
    def _credential_token(
        *,
        authorization: str | None,
        session_cookie: str | None,
        websocket_protocols: str | None,
    ) -> tuple[str, bool] | None:
        bearer = SecurityService._bearer_token(authorization)
        websocket_session = SecurityService._websocket_session_token(websocket_protocols)
        supplied = [
            value
            for value in (
                (bearer, True) if bearer is not None else None,
                (session_cookie.strip(), False) if session_cookie else None,
                (websocket_session, False) if websocket_session is not None else None,
            )
            if value
        ]
        if len(supplied) > 1:
            raise SecurityViolation("AMBIGUOUS_CREDENTIALS", "Supply exactly one credential")
        return supplied[0] if supplied else None

    @staticmethod
    def _bearer_token(value: str | None) -> str | None:
        if value is None:
            return None
        scheme, separator, token = value.partition(" ")
        if (
            not separator
            or scheme.casefold() != "bearer"
            or not token.strip()
            or " " in token.strip()
        ):
            raise SecurityViolation("AUTH_INVALID", "Authorization must contain one Bearer token")
        return token.strip()

    @staticmethod
    def _websocket_session_token(value: str | None) -> str | None:
        if value is None:
            return None
        matches = [
            item.strip().removeprefix("momo.session.")
            for item in value.split(",")
            if item.strip().startswith("momo.session.")
        ]
        if len(matches) > 1:
            raise SecurityViolation("AMBIGUOUS_CREDENTIALS", "Supply one WebSocket session")
        return matches[0] if matches else None

    def issue_session(
        self,
        *,
        authorization: str,
        principal_id: str,
        surfaces: Collection[SecuritySurface],
        ttl: timedelta = timedelta(minutes=30),
    ) -> IssuedSession:
        principal = self.authorize(
            surface=SecuritySurface.REST,
            authorization=authorization,
        )
        if principal.authentication != "LONG_TERM_TOKEN":
            raise SecurityViolation("LONG_TERM_AUTH_REQUIRED", "A long-term token is required")
        if not timedelta(seconds=30) <= ttl <= timedelta(hours=12):
            raise SecurityViolation("SESSION_TTL_INVALID", "Session TTL is outside the safe bound")
        allowed = frozenset(surfaces)
        if not allowed:
            raise SecurityViolation("SESSION_SCOPE_INVALID", "Session requires at least one scope")
        self._prune_sessions()
        if len(self._sessions) >= self._max_sessions:
            raise SecurityViolation("SESSION_CAPACITY", "Session capacity has been reached")
        now = self._now()
        token = secrets.token_urlsafe(32)
        grant = SessionGrant(
            principal_id=principal_id,
            issued_at=now,
            expires_at=now + ttl,
            surfaces=allowed,
        )
        digest = self._digest(token)
        self._sessions[digest] = _StoredSession(digest=digest, grant=grant)
        return IssuedSession(token=token, grant=grant)

    def _prune_sessions(self) -> None:
        now = self._now()
        for digest, stored in tuple(self._sessions.items()):
            if stored.grant.expires_at <= now:
                del self._sessions[digest]

    def revoke_session(self, token: str) -> bool:
        return self._sessions.pop(self._digest(token), None) is not None

    def authorize_control(self, **credentials: Any) -> AuthorizedPrincipal:
        principal = self.authorize(surface=SecuritySurface.CONTROL, **credentials)
        self.control_rate_limiter.consume(principal.principal_id)
        return principal

    def audit(
        self,
        *,
        request_id: str,
        source: str,
        outcome: AuditOutcome,
        duration_ms: float,
        command_id: str | None = None,
        robot_id: str | None = None,
        principal_id: str | None = None,
        mode: str | None = None,
        preflight: str | None = None,
        error_code: str | None = None,
        details: Mapping[str, object] | None = None,
    ) -> SecurityAuditEvent:
        safe_details = redact_for_log(details or {})
        if not isinstance(safe_details, dict):  # pragma: no cover - Mapping guarantees this
            safe_details = {}
        event = SecurityAuditEvent(
            occurred_at=self._now(),
            request_id=request_id,
            command_id=command_id,
            robot_id=robot_id,
            principal_id=principal_id,
            source=redact_text(source),
            mode=redact_text(mode) if mode is not None else None,
            preflight=redact_text(preflight) if preflight is not None else None,
            outcome=outcome,
            duration_ms=duration_ms,
            error_code=error_code,
            details=safe_details,
        )
        self.audit_sink.emit(event)
        return event
