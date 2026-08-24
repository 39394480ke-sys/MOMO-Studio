"""Optional same-origin frontend hosting with safe SPA refresh fallback."""

from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path, PurePosixPath
from typing import Any

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles


class SpaStaticFiles(StaticFiles):
    """Serve a built frontend without turning missing API/assets into fake HTML success."""

    def __init__(self, directory: Path) -> None:
        resolved = directory.resolve()
        if not resolved.is_dir() or not (resolved / "index.html").is_file():
            raise ValueError("frontend distribution must contain index.html")
        super().__init__(directory=resolved, html=True, check_dir=True)

    async def get_response(self, path: str, scope: MutableMapping[str, Any]) -> Response:
        normalized = path.lstrip("/")
        leaf = PurePosixPath(normalized).name
        may_fallback = (
            scope.get("method") in {"GET", "HEAD"}
            and not normalized.startswith("api/")
            and "." not in leaf
        )
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404 or not may_fallback:
                raise
            fallback = await super().get_response("index.html", scope)
            fallback.headers["Cache-Control"] = "no-store"
            return fallback
        if response.status_code != 404:
            if PurePosixPath(path).name == "index.html":
                response.headers["Cache-Control"] = "no-store"
            return response

        if not may_fallback:
            return response
        fallback = await super().get_response("index.html", scope)
        fallback.headers["Cache-Control"] = "no-store"
        return fallback
