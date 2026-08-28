"""Uniform error envelopes without Python exception leakage."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from momo.api.schemas import ErrorResponse
from momo.domain.errors import RobotApplicationError


def _response(error: ErrorResponse, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error.model_dump(mode="json"))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RobotApplicationError)
    async def application_error(
        request: Request,
        error: RobotApplicationError,
    ) -> JSONResponse:
        request.state.error_code = error.code
        return _response(
            ErrorResponse(
                code=error.code,
                message=error.message,
                details=error.details if error.details is not None else {},
            ),
            error.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        request.state.error_code = "REQUEST_VALIDATION_ERROR"
        details = [
            {"location": list(item["loc"]), "message": item["msg"]} for item in error.errors()
        ]
        return _response(
            ErrorResponse(
                code="REQUEST_VALIDATION_ERROR",
                message="Request validation failed",
                details={"issues": details},
            ),
            422,
        )

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception) -> JSONResponse:
        request.state.error_code = "INTERNAL_ERROR"
        del error
        return _response(
            ErrorResponse(
                code="INTERNAL_ERROR",
                message="An internal error occurred",
                details={},
            ),
            500,
        )
