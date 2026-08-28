"""Pure network-exposure and audit contracts for MOMO Studio.

This module deliberately has no socket, environment, or web-framework side effects.
Binding a server remains an explicit deployment decision made outside the domain.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

LOCAL_BIND_HOST = "127.0.0.1"
DEFAULT_MAX_REQUEST_BODY_BYTES = 2 * 1024 * 1024
MAX_SECURITY_SESSIONS = 1024
MAX_RATE_LIMIT_PRINCIPALS = 1024

BoundedIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
BoundedText = Annotated[str, StringConstraints(max_length=500)]


class NetworkExposureMode(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    LAN = "LAN"


class SecuritySurface(StrEnum):
    REST = "REST"
    CONTROL = "CONTROL"
    WEBSOCKET = "WEBSOCKET"
    VISION = "VISION"


class SecurityViolation(ValueError):
    """Stable, non-secret reason for a denied security decision."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower().removeprefix("[").removesuffix("]")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def is_private_lan_host(host: str) -> bool:
    """Accept only a concrete private address; never wildcard/public hostnames."""

    normalized = host.strip().lower().removeprefix("[").removesuffix("]")
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return bool(
        (address.is_private or address.is_loopback)
        and not address.is_unspecified
        and not address.is_multicast
        and not address.is_reserved
    )


def normalize_origin(origin: str) -> str:
    """Return an exact allowlist key or reject a loose/wildcard origin."""

    candidate = origin.strip()
    if not candidate or candidate in {"*", "null"}:
        raise ValueError("wildcard and opaque origins are not allowed")
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("origin must be an absolute http(s) origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("origin must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("origin must not contain a path")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("origin port is invalid") from error
    host = parsed.hostname.lower()
    display_host = f"[{host}]" if ":" in host else host
    default_port = 80 if parsed.scheme == "http" else 443
    authority = display_host if port in {None, default_port} else f"{display_host}:{port}"
    return f"{parsed.scheme}://{authority}"


class NetworkSecurityPolicy(BaseModel):
    """Validated, side-effect-free decision describing an allowed bind."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    exposure_mode: NetworkExposureMode = NetworkExposureMode.LOCAL_ONLY
    bind_host: BoundedIdentifier = LOCAL_BIND_HOST
    lan_enabled: bool = False
    allowed_origins: tuple[str, ...] = ()
    require_authentication: bool = False
    max_request_body_bytes: Annotated[int, Field(strict=True, ge=1024, le=32 * 1024 * 1024)] = (
        DEFAULT_MAX_REQUEST_BODY_BYTES
    )

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(normalize_origin(origin) for origin in value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("allowed_origins must be unique after normalization")
        return normalized

    @model_validator(mode="after")
    def validate_exposure(self) -> Self:
        if self.exposure_mode is NetworkExposureMode.LOCAL_ONLY:
            if self.lan_enabled:
                raise ValueError("lan_enabled is incompatible with LOCAL_ONLY mode")
            if not is_loopback_host(self.bind_host):
                raise ValueError("LOCAL_ONLY mode requires a loopback bind host")
            for origin in self.allowed_origins:
                if not is_loopback_host(urlsplit(origin).hostname or ""):
                    raise ValueError("LOCAL_ONLY origins must use a loopback host")
            return self

        if not self.lan_enabled:
            raise ValueError("LAN exposure requires an explicit lan_enabled decision")
        if not self.require_authentication:
            raise ValueError("LAN exposure requires authentication")
        if not is_private_lan_host(self.bind_host):
            raise ValueError("LAN bind_host must be a concrete private address")
        normalized_bind_host = self.bind_host.strip().lower().removeprefix("[").removesuffix("]")
        for origin in self.allowed_origins:
            parsed_origin = urlsplit(origin)
            origin_host = (parsed_origin.hostname or "").lower()
            if not is_private_lan_host(origin_host):
                raise ValueError("LAN origins must use concrete private or loopback addresses")
            if parsed_origin.scheme != "http":
                raise ValueError(
                    "LAN browser origins must use the HTTP scheme supported by this server"
                )
            if origin_host != normalized_bind_host:
                raise ValueError(
                    "LAN browser origins must use the API bind host so the Strict session "
                    "cookie remains same-site"
                )
        return self

    def allows_origin(self, origin: str | None, *, required: bool = False) -> bool:
        if origin is None:
            return not required
        try:
            normalized = normalize_origin(origin)
        except ValueError:
            return False
        return normalized in self.allowed_origins


class AuthorizedPrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    principal_id: BoundedIdentifier
    authentication: Literal["LOCAL", "LONG_TERM_TOKEN", "SESSION"]
    surfaces: frozenset[SecuritySurface]
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def require_aware_expiry(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("expires_at must include a timezone offset")
        return value


class SessionGrant(BaseModel):
    """Session metadata. The one-time token is intentionally not a model field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    principal_id: BoundedIdentifier
    issued_at: datetime
    expires_at: datetime
    surfaces: frozenset[SecuritySurface]

    @field_validator("issued_at", "expires_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("session timestamps must include a timezone offset")
        return value

    @model_validator(mode="after")
    def require_future_expiry(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("session expiry must be later than issuance")
        return self


class AuditOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SecurityAuditEvent(BaseModel):
    """Bounded structured event; sensitive credential fields are absent by design."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    occurred_at: datetime
    request_id: BoundedIdentifier
    command_id: BoundedIdentifier | None = None
    robot_id: BoundedIdentifier | None = None
    principal_id: BoundedIdentifier | None = None
    source: BoundedText
    mode: BoundedText | None = None
    preflight: BoundedText | None = None
    outcome: AuditOutcome
    duration_ms: Annotated[float, Field(strict=True, ge=0, le=86_400_000, allow_inf_nan=False)]
    error_code: BoundedIdentifier | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def require_aware_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone offset")
        return value
