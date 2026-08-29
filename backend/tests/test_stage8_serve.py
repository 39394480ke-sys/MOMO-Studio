"""Safe serving entry-point tests; no test binds a socket."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import uvicorn
from pydantic import ValidationError

from momo import serve
from momo.settings import Settings


def test_supervised_serve_uses_explicit_config_and_validated_bind_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_config = tmp_path / "momo.local.yaml"
    local_config.write_text("server_host: 127.0.0.1\nserver_port: 8123\n", encoding="utf-8")
    settings = Settings(server_host="127.0.0.1", server_port=8123)
    created_with: list[Settings] = []
    config_calls: list[tuple[object, dict[str, object]]] = []
    app_sentinel = object()

    class FakeController:
        restart_requested = False

        def __init__(self, path: Path) -> None:
            assert path == local_config.resolve()

        def selected_settings(self) -> Settings:
            return settings

        def bind_restart(self, callback: object) -> None:
            assert callable(callback)

    def fake_create_app(*, settings: Settings, runtime_mode_control: object) -> object:
        created_with.append(settings)
        assert isinstance(runtime_mode_control, FakeController)
        return app_sentinel

    def fake_config(app: object, **kwargs: object) -> object:
        config_calls.append((app, kwargs))
        return object()

    class FakeServer:
        should_exit = False

        def __init__(self, config: object) -> None:
            del config

        async def serve(self) -> None:
            return None

    monkeypatch.setattr(serve, "LocalRuntimeModeController", FakeController)
    monkeypatch.setattr(serve, "create_app", fake_create_app)
    monkeypatch.setattr(uvicorn, "Config", fake_config)
    monkeypatch.setattr(uvicorn, "Server", FakeServer)

    asyncio.run(serve._serve_supervised(local_config.resolve()))

    assert created_with == [settings]
    assert config_calls == [
        (
            app_sentinel,
            {
                "host": "127.0.0.1",
                "port": 8123,
                "access_log": False,
                "proxy_headers": False,
                "server_header": False,
            },
        )
    ]


def test_serve_rejects_missing_config_and_has_no_host_or_port_override(
    tmp_path: Path,
) -> None:
    with pytest.raises(SystemExit):
        serve.main(["--local-config", str(tmp_path / "missing.yaml")])

    local_config = tmp_path / "momo.local.yaml"
    local_config.write_text("{}\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        serve.main(
            [
                "--local-config",
                str(local_config),
                "--host",
                "0.0.0.0",
                "--port",
                "80",
            ]
        )


@pytest.mark.parametrize("port", [0, 80, 65536, True])
def test_server_port_is_strictly_validated_before_serving(port: object) -> None:
    with pytest.raises(ValidationError):
        Settings(server_port=port)  # type: ignore[arg-type]


def test_local_only_settings_never_accept_a_wildcard_bind() -> None:
    with pytest.raises(ValidationError, match="non-loopback"):
        Settings(server_host="0.0.0.0")
