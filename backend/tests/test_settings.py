"""Configuration precedence and safety-lock tests (requirement 19)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from momo.domain.enums import ControlMode, HardwareAccessPolicy, RobotVariant
from momo.domain.vision import CameraAccessPolicy
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
    assert settings.camera_access_policy is CameraAccessPolicy.SYNTHETIC_ONLY
    assert settings.operator_session_ttl_s == 300
    assert settings.browser_security_session_ttl_s == 1800


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operator_session_ttl_s", 29),
        ("operator_session_ttl_s", 901),
        ("browser_security_session_ttl_s", 29),
        ("browser_security_session_ttl_s", 43_201),
    ],
)
def test_hardware_and_browser_session_ttls_have_independent_safe_bounds(
    field: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({field: value})

    valid = Settings(
        operator_session_ttl_s=900,
        browser_security_session_ttl_s=43_200,
    )
    assert valid.operator_session_ttl_s == 900
    assert valid.browser_security_session_ttl_s == 43_200

    properties = Settings.model_json_schema()["properties"]
    assert properties["operator_session_ttl_s"] == {
        "default": 300,
        "maximum": 900,
        "minimum": 30,
        "title": "Operator Session Ttl S",
        "type": "integer",
    }
    assert properties["browser_security_session_ttl_s"] == {
        "default": 1800,
        "maximum": 43_200,
        "minimum": 30,
        "title": "Browser Security Session Ttl S",
        "type": "integer",
    }


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


def test_ignored_local_config_is_read_only_when_explicitly_requested(tmp_path: Path) -> None:
    default = tmp_path / "default.yaml"
    local = tmp_path / "local.yaml"
    default.write_text("active_robot_variant: V1\n", encoding="utf-8")
    local.write_text("active_robot_variant: V2\n", encoding="utf-8")

    implicit = load_settings(default_config_path=default)
    explicit = load_settings(default_config_path=default, local_config_path=local)

    assert implicit.active_robot_variant is RobotVariant.V1
    assert explicit.active_robot_variant is RobotVariant.V2


def test_stage_eight_accepts_partial_real_configuration_without_granting_hardware(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(real_motion_enabled=True)
    assert settings.real_motion_enabled is True
    assert settings.hardware_startup_enabled is False
    assert settings.hardware_local_config_enabled is False
    real_motion_field = "real_motion_enabled"
    with pytest.raises(ValidationError, match="Instance is frozen"):
        setattr(settings, real_motion_field, True)

    monkeypatch.setenv("MOMO_REAL_MOTION_ENABLED", "true")
    loaded = load_settings(default_config_path=tmp_path / "missing.yaml")
    assert loaded.real_motion_enabled is True
    assert loaded.hardware_local_config_enabled is False


@pytest.mark.parametrize(
    "policy",
    [HardwareAccessPolicy.READ_ONLY, HardwareAccessPolicy.FULL],
)
def test_stage_eight_preserves_non_disabled_policy_as_readiness_evidence(
    policy: HardwareAccessPolicy,
) -> None:
    settings = Settings(hardware_access_policy=policy)
    assert settings.hardware_access_policy is policy
    assert settings.hardware_startup_enabled is False
    assert settings.hardware_local_config_enabled is False


def test_hardware_local_authorization_requires_exact_explicit_local_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default = tmp_path / "default.yaml"
    default.write_text("hardware_access: disabled\n", encoding="utf-8")
    monkeypatch.setenv("MOMO_HARDWARE_LOCAL_CONFIG_ENABLED", "true")
    monkeypatch.setenv("MOMO_SERIAL_PORT", "/dev/explicit-test-only")
    monkeypatch.setenv("MOMO_SERVO_IDS", "[1,2]")
    monkeypatch.setenv("MOMO_SERVO_PROTOCOL", "sts")
    with pytest.raises(ValueError, match="explicitly supplied local config"):
        load_settings(default_config_path=default)

    local = tmp_path / "local.yaml"
    local.write_text(
        "hardware_local_config_enabled: true\n"
        "robot_unit_id: MOMO-V2-UNIT-SYNTHETIC\n"
        "serial_port: /dev/explicit-test-only\n"
        "servo_ids: [1, 2]\n"
        "servo_protocol: sts\n",
        encoding="utf-8",
    )
    configured = load_settings(default_config_path=default, local_config_path=local)
    assert configured.hardware_local_config_enabled is True
    assert configured.robot_unit_id == "MOMO-V2-UNIT-SYNTHETIC"
    assert configured.servo_ids == (1, 2)

    monkeypatch.setenv("MOMO_SERIAL_PORT", "/dev/environment-mismatch")
    with pytest.raises(ValueError, match="exact device"):
        load_settings(
            default_config_path=default,
            local_config_path=local,
        )


def test_feetech_read_only_adapter_requires_complete_local_read_only_gate(
    tmp_path: Path,
) -> None:
    default = tmp_path / "default.yaml"
    default.write_text("control_mode: dry_run\n", encoding="utf-8")
    local = tmp_path / "local.yaml"
    local.write_text(
        "control_mode: real\n"
        "real_motion_enabled: false\n"
        "commissioning_motion_test_enabled: false\n"
        "hardware_access_policy: read_only\n"
        "hardware_startup_enabled: true\n"
        "hardware_local_config_enabled: true\n"
        "feetech_read_only_adapter_enabled: true\n"
        "robot_unit_id: MOMO-V2-UNIT-SYNTHETIC\n"
        "serial_port: /dev/explicit-test-only\n"
        "servo_ids: [10, 11, 12, 13, 14, 15]\n"
        "servo_protocol: STS3215\n",
        encoding="utf-8",
    )
    configured = load_settings(default_config_path=default, local_config_path=local)
    assert configured.control_mode is ControlMode.REAL
    assert configured.hardware_access_policy is HardwareAccessPolicy.READ_ONLY
    assert configured.feetech_read_only_adapter_enabled is True
    assert configured.real_motion_enabled is False

    local.write_text(
        local.read_text().replace(
            "hardware_access_policy: read_only",
            "hardware_access_policy: full",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="READ_ONLY"):
        load_settings(default_config_path=default, local_config_path=local)


def test_real_control_mode_is_only_one_readiness_input() -> None:
    settings = Settings(control_mode=ControlMode.REAL)
    assert settings.control_mode is ControlMode.REAL
    assert settings.real_motion_enabled is False
    assert settings.hardware_access_policy is HardwareAccessPolicy.DISABLED


def test_local_origins_are_explicit_loopback_values() -> None:
    settings = Settings()
    assert "http://127.0.0.1:5173" in settings.local_allowed_origins
    assert "http://localhost:8000" in settings.local_allowed_origins
    with pytest.raises(ValidationError, match="Local Origins"):
        Settings(local_allowed_origins=("http://evil.example",))


@pytest.mark.parametrize(
    ("motion_directory", "draft_directory"),
    [
        ("entities", "entities"),
        ("entities", "entities/drafts"),
        ("entities/motions", "entities"),
    ],
)
def test_storage_directories_must_not_overlap_before_repository_access(
    tmp_path: Path,
    motion_directory: str,
    draft_directory: str,
) -> None:
    shared_root = tmp_path / "storage"
    formal_motion = shared_root / motion_directory / "00000000-0000-4000-8000-000000000001.json"
    formal_motion.parent.mkdir(parents=True)
    formal_motion.write_text('{"sentinel":"formal-motion"}\n', encoding="utf-8")

    with pytest.raises(ValidationError, match="storage directories must not overlap"):
        Settings(
            motion_library_directory=str(shared_root / motion_directory),
            motion_draft_directory=str(shared_root / draft_directory),
        )

    assert formal_motion.read_text(encoding="utf-8") == '{"sentinel":"formal-motion"}\n'
    assert not (formal_motion.parent / "quarantine").exists()


def test_storage_directories_reject_existing_case_alias_before_repository_access(
    tmp_path: Path,
) -> None:
    formal_directory = tmp_path / "Motions"
    formal_directory.mkdir()
    sentinel = formal_directory / "00000000-0000-4000-8000-000000000001.json"
    sentinel.write_text('{"sentinel":"formal-motion"}\n', encoding="utf-8")

    with pytest.raises(ValidationError, match="storage directories must not overlap"):
        Settings(
            motion_library_directory=str(formal_directory),
            motion_draft_directory=str(tmp_path / "motions"),
        )

    assert sentinel.read_text(encoding="utf-8") == '{"sentinel":"formal-motion"}\n'
    assert not (formal_directory / "quarantine").exists()


def test_storage_directories_conservatively_reject_uncreated_case_aliases(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match="storage directories must not overlap"):
        Settings(
            motion_library_directory=str(tmp_path / "Future" / "Motions"),
            motion_draft_directory=str(tmp_path / "future" / "motions"),
        )

    assert not (tmp_path / "Future").exists()


@pytest.mark.parametrize("update_hz", [0.1, 19.999, 100.001])
def test_motion_update_rate_has_reviewed_interpolation_bounds(update_hz: float) -> None:
    with pytest.raises(ValidationError):
        Settings(motion_update_hz=update_hz)


def test_live_camera_policy_requires_device_and_explicit_local_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError, match="live_camera_device_id"):
        Settings(camera_access_policy=CameraAccessPolicy.LIVE_CAMERA_ALLOWED)

    default = tmp_path / "default.yaml"
    default.write_text(
        "camera_access_policy: synthetic_only\nlive_camera_device_id: ''\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MOMO_CAMERA_ACCESS_POLICY", "LIVE_CAMERA_ALLOWED")
    monkeypatch.setenv("MOMO_LIVE_CAMERA_DEVICE_ID", "explicit-device")
    monkeypatch.setenv("MOMO_LIVE_CAMERA_LOCAL_CONFIG_ENABLED", "true")
    with pytest.raises(ValueError, match="explicitly supplied local config"):
        load_settings(default_config_path=default)

    local = tmp_path / "local.yaml"
    local.write_text(
        "camera_access_policy: live_camera_allowed\n"
        "live_camera_device_id: explicit-device\n"
        "live_camera_local_config_enabled: true\n",
        encoding="utf-8",
    )
    configured = load_settings(default_config_path=default, local_config_path=local)
    assert configured.camera_access_policy is CameraAccessPolicy.LIVE_CAMERA_ALLOWED
    assert configured.live_camera_device_id == "explicit-device"
    assert configured.live_camera_local_config_enabled is True


@pytest.mark.parametrize(
    ("width_px", "height_px"),
    [(63, 360), (1281, 360), (640, 63), (640, 721)],
)
def test_synthetic_frame_resolution_has_reviewed_bounds(
    width_px: int,
    height_px: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            vision_frame_width_px=width_px,
            vision_frame_height_px=height_px,
        )
