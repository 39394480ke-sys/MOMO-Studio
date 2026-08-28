"""Stage 8 same-origin frontend hosting and refresh-route isolation."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from momo.api.app import create_app
from momo.settings import Settings


def test_static_hosting_supports_spa_refresh_without_masking_api_or_assets(
    tmp_path: Path,
) -> None:
    distribution = tmp_path / "dist"
    assets = distribution / "assets"
    assets.mkdir(parents=True)
    (distribution / "index.html").write_text("<main>MOMO RC</main>\n", encoding="utf-8")
    (assets / "app.js").write_text("export const ready = true;\n", encoding="utf-8")
    app = create_app(
        Settings(
            serve_frontend_static=True,
            frontend_dist_directory=str(distribution),
        )
    )

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            refresh = await client.get("/settings")
            assert refresh.status_code == 200
            assert refresh.text == "<main>MOMO RC</main>\n"
            assert refresh.headers["cache-control"] == "no-store"

            asset = await client.get("/assets/app.js")
            assert asset.status_code == 200
            assert "ready = true" in asset.text

            missing_asset = await client.get("/assets/missing.js")
            assert missing_asset.status_code == 404

            missing_api = await client.get("/api/v1/not-a-route")
            assert missing_api.status_code == 404
            assert "MOMO RC" not in missing_api.text

    asyncio.run(exercise())


def test_static_hosting_fails_closed_without_a_built_index(tmp_path: Path) -> None:
    distribution = tmp_path / "empty-dist"
    distribution.mkdir()
    try:
        create_app(
            Settings(
                serve_frontend_static=True,
                frontend_dist_directory=str(distribution),
            )
        )
    except ValueError as error:
        assert "index.html" in str(error)
    else:  # pragma: no cover - explicit fail-closed assertion
        raise AssertionError("missing frontend build was accepted")


def test_static_distribution_cannot_overlap_private_storage(tmp_path: Path) -> None:
    distribution = tmp_path / "public-parent"
    private_calibrations = distribution / "real-calibrations"
    private_calibrations.mkdir(parents=True)
    (distribution / "index.html").write_text("<main>public</main>\n", encoding="utf-8")
    (private_calibrations / "v2.current.json").write_text(
        '{"private":"must-not-be-served"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="frontend_dist_directory"):
        Settings(
            serve_frontend_static=True,
            frontend_dist_directory=str(distribution),
            real_calibration_directory=str(private_calibrations),
        )


def test_release_app_disables_cdn_backed_interactive_api_docs() -> None:
    async def exercise() -> None:
        app = create_app(Settings())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/docs")).status_code == 404
            assert (await client.get("/redoc")).status_code == 404
            schema = await client.get("/openapi.json")
            assert schema.status_code == 200
            assert "cdn.jsdelivr.net" not in schema.text
            assert "http://" not in schema.text
            assert "https://" not in schema.text

    asyncio.run(exercise())
