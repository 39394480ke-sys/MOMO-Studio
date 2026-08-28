"""Supported, fail-closed Uvicorn entry point for local and explicit LAN serving."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from momo.api.app import create_app
from momo.settings import load_settings


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


def main(argv: Sequence[str] | None = None) -> None:
    """Load one explicit local config before constructing or binding the application."""

    parser = build_parser()
    arguments = parser.parse_args(argv)
    local_config = Path(arguments.local_config).expanduser()
    if not local_config.is_file():
        parser.error("--local-config must name an existing regular file")
    local_config = local_config.resolve(strict=True)

    settings = load_settings(local_config_path=local_config)
    app = create_app(settings=settings)
    uvicorn.run(
        app,
        host=settings.server_host,
        port=settings.server_port,
        access_log=False,
        proxy_headers=False,
        server_header=False,
    )


if __name__ == "__main__":  # pragma: no cover - exercised through the installed script
    main()
