"""Configuration precedence and safety-lock tests (requirement 19)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from momo.domain.enums import ControlMode, HardwareAccessPolicy, RobotVariant
from momo.settings import Settings, load_settings


def test_defaults_are_always_dry_run_when_config_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MOMO_CONTROL_MODE", raising=False)
    monkeypatch.delenv("MOMO_REAL_MOTION_ENABLED", raising=False)
    settings = load_settings(
        default_config_path=tmp_path / "missing-default.yaml",
        local_config_path=tmp_path / "missing-local.yaml",
    )
    assert settings.control_mode is ControlMode.DRY_RUN
    assert settings.real_motion_enabled is False
    assert settings.active_robot_variant is RobotVariant.V2
    assert settings.hardware_access_policy is HardwareAccessPolicy.DISABLED


def test_environment_overrides_yaml_without_using_current_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "default.yaml"
    config.write_text(
        "control_mode: dry_run\nactive_robot_variant: V1\nserial_port: ''\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MOMO_ACTIVE_ROBOT_VARIANT", "v2")
    monkeypatch.setenv("MOMO_SERIAL_PORT", "/dev/example-not-opened")
    settings = load_settings(
        default_config_path=config,
        local_config_path=tmp_path / "missing-local.yaml",
    )
    assert settings.active_robot_variant is RobotVariant.V2
    assert settings.serial_port == "/dev/example-not-opened"


def test_stage_two_rejects_every_attempt_to_enable_real_motion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError, match="locked to false"):
        Settings(real_motion_enabled=True)

    settings = Settings()
    with pytest.raises(ValidationError, match="Instance is frozen"):
        settings.real_motion_enabled = True

    monkeypatch.setenv("MOMO_REAL_MOTION_ENABLED", "true")
    with pytest.raises(ValidationError, match="locked to false"):
        load_settings(
            default_config_path=tmp_path / "missing.yaml",
            local_config_path=tmp_path / "missing-local.yaml",
        )


@pytest.mark.parametrize(
    "policy",
    [HardwareAccessPolicy.READ_ONLY, HardwareAccessPolicy.FULL],
)
def test_stage_two_rejects_non_disabled_hardware_policy(policy: HardwareAccessPolicy) -> None:
    with pytest.raises(ValidationError, match="hardware_access=DISABLED"):
        Settings(hardware_access_policy=policy)


def test_yaml_and_environment_cannot_override_hardware_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "unsafe.yaml"
    config.write_text("hardware_access: read_only\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="hardware_access=DISABLED"):
        load_settings(
            default_config_path=config,
            local_config_path=tmp_path / "missing-local.yaml",
        )

    config.write_text("hardware_access: disabled\n", encoding="utf-8")
    monkeypatch.setenv("MOMO_HARDWARE_ACCESS_POLICY", "full")
    with pytest.raises(ValidationError, match="hardware_access=DISABLED"):
        load_settings(
            default_config_path=config,
            local_config_path=tmp_path / "missing-local.yaml",
        )


def test_stage_two_rejects_real_control_mode() -> None:
    with pytest.raises(ValidationError, match="control_mode=DRY_RUN"):
        Settings(control_mode=ControlMode.REAL)
