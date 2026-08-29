"""Supported, fail-closed Uvicorn entry point for local and explicit LAN serving."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from functools import partial
from pathlib import Path

import uvicorn

from momo.api.app import create_app
from momo.runtime_mode import LocalRuntimeModeController


def _schedule_restart(loop: asyncio.AbstractEventLoop, server: uvicorn.Server) -> None:
    loop.call_later(0.15, setattr, server, "should_exit", True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="momo-studio-serve",
        description=(
            "Serve MOMO Studio using a validated ignored local YAML configuration. "
            "Host and port cannot be overridden on the command line."
        ),
    )
    parser.add_argument(
        "--local-config",
        required=True,
        metavar="PATH",
        help="explicit path to an existing ignored local YAML configuration",
    )
    return parser


async def _serve_supervised(local_config: Path) -> None:
    """Gracefully rebuild the product graph after an explicit local mode switch."""

    while True:
        controller = LocalRuntimeModeController(local_config)
        settings = controller.selected_settings()
        app = create_app(settings=settings, runtime_mode_control=controller)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=settings.server_host,
                port=settings.server_port,
                access_log=False,
                proxy_headers=False,
                server_header=False,
            )
        )
        loop = asyncio.get_running_loop()
        controller.bind_restart(partial(_schedule_restart, loop, server))
        await server.serve()
        if not controller.restart_requested:
            return


def main(argv: Sequence[str] | None = None) -> None:
    """Run one explicit local config under the mode-switch supervisor."""

    parser = build_parser()
    arguments = parser.parse_args(argv)
    local_config = Path(arguments.local_config).expanduser()
    if not local_config.is_file():
        parser.error("--local-config must name an existing regular file")
    local_config = local_config.resolve(strict=True)

    asyncio.run(_serve_supervised(local_config))


if __name__ == "__main__":  # pragma: no cover - exercised through the installed script
    main()
