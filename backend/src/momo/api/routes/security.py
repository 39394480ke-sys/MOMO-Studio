"""LAN browser-session exchange without exposing a token in JSON or a URL."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict

from momo.api.dependencies import get_settings
from momo.api.security import (
    SecurityServiceDependency,
    SessionCookie,
    clear_session_cookie,
    security_http_error,
    set_session_cookie,
)
from momo.domain.security import SecuritySurface, SecurityViolation
from momo.settings import Settings

router = APIRouter(prefix="/security", tags=["security"])
SettingsDependency = Annotated[Settings, Depends(get_settings)]
BearerAuthorization = Annotated[
    str,
    Header(alias="Authorization", min_length=8, max_length=600),
]


class SecuritySessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str
    issued_at: datetime
    expires_at: datetime
    surfaces: list[SecuritySurface]


@router.post("/session", response_model=SecuritySessionResponse)
async def issue_browser_session(
    request: Request,
    response: Response,
    authorization: BearerAuthorization,
    service: SecurityServiceDependency,
    settings: SettingsDependency,
) -> SecuritySessionResponse:
    """Exchange the configured LAN Bearer token for one HttpOnly scoped cookie."""

    # Deliberately validate the explicit long-term Bearer independently of any stale
    # HttpOnly cookie retained across a backend restart. A valid bearer replaces that
    # cookie; generic endpoints still reject multiple credentials as ambiguous.
    try:
        principal = service.authorize(
            surface=SecuritySurface.REST,
            authorization=authorization,
            query_keys=tuple(request.query_params.keys()),
        )
    except SecurityViolation as error:
        raise security_http_error(error) from error
    if principal.authentication != "LONG_TERM_TOKEN":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "LAN_SESSION_NOT_REQUIRED",
                "message": "Browser sessions are issued only in authenticated LAN mode",
            },
        )
    surfaces = tuple(SecuritySurface)
    try:
        issued = service.issue_session(
            authorization=authorization,
            principal_id=principal.principal_id,
            surfaces=surfaces,
            ttl=timedelta(seconds=settings.operator_session_ttl_s),
        )
    except SecurityViolation as error:
        raise security_http_error(error) from error
    set_session_cookie(response, issued, secure=request.url.scheme == "https")
    grant = issued.grant
    return SecuritySessionResponse(
        principal_id=grant.principal_id,
        issued_at=grant.issued_at,
        expires_at=grant.expires_at,
        surfaces=sorted(grant.surfaces, key=lambda item: item.value),
    )


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_browser_session(
    request: Request,
    response: Response,
    service: SecurityServiceDependency,
    session_cookie: SessionCookie = None,
) -> None:
    """Clear the browser cookie even when the server-side grant already expired."""

    try:
        service.reject_query_credentials(tuple(request.query_params.keys()))
    except SecurityViolation as error:
        raise security_http_error(error) from error
    if session_cookie:
        service.revoke_session(session_cookie)
    clear_session_cookie(response, secure=request.url.scheme == "https")
    response.headers["Cache-Control"] = "no-store"
