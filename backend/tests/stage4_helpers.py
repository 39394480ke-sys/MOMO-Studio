"""Synthetic Stage 4 app and HTTP fixtures with isolated data directories."""

from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import FastAPI

from momo.api.app import create_app
from momo.settings import Settings


def make_stage4_app(tmp_path: Path) -> FastAPI:
    return create_app(
        Settings(
            runtime_state_directory=str(tmp_path / "runtime"),
            pose_directory=str(tmp_path / "poses"),
            motion_library_directory=str(tmp_path / "motions"),
            calibration_directory=str(tmp_path / "no-calibration"),
        )
    )


async def api_request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json_data: object | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=json_data)
