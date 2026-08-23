"""FastAPI dependencies sourced from app state, not process globals."""

from typing import cast

from fastapi import Request

from momo.settings import Settings


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)
