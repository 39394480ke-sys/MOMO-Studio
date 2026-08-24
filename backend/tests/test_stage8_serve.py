"""Safe serving entry-point tests; no test binds a socket."""

from __future__ import annotations

from pathlib import Path

import pytest
import uvicorn
from pydantic import ValidationError

from momo import serve
from momo.settings import Settings


def test_serve_loads_only_the_explicit_local_config_and_binds_validated_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_config = tmp_path / "momo.local.yaml"
    local_config.write_text("server_host: 127.0.0.1\nserver_port: 8123\n", encoding="utf-8")
    settings = Settings(server_host="127.0.0.1", server_port=8123)
    loaded_paths: list[Path] = []
    created_with: list[Settings] = []
    run_calls: list[tuple[object, dict[str, object]]] = []
    app_sentinel = object()

    def fake_load_settings(
        default_config_path: Path | None = None,
        local_config_path: Path | None = None,
    ) -> Settings:
        assert default_config_path is None
        assert local_config_path is not None
        loaded_paths.append(local_config_path)
        return settings

    def fake_create_app(*, settings: Settings) -> object:
        created_with.append(settings)
        return app_sentinel

    def fake_run(app: object, **kwargs: object) -> None:
        run_calls.append((app, kwargs))

    monkeypatch.setattr(serve, "load_settings", fake_load_settings)
    monkeypatch.setattr(serve, "create_app", fake_create_app)
    monkeypatch.setattr(uvicorn, "run", fake_run)

    serve.main(["--local-config", str(local_config)])

    assert loaded_paths == [local_config.resolve()]
    assert created_with == [settings]
    assert run_calls == [
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
