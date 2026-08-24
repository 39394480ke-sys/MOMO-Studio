"""Synthetic Stage 8 hardware authorization fixtures; never real device data."""

from __future__ import annotations

from typing import Any, cast

from momo.adapters.hardware.fake_servo_bus import FakeServoBus, FakeServoBusFactory
from momo.adapters.kinematics.model_repository import FileKinematicsModelRepository
from momo.application.services.device_diagnostics_service import DeviceDiagnosticsService
from momo.application.services.operator_session_service import OperatorSessionService
from momo.application.services.real_hardware_authorization import RealHardwareAuthorization
from momo.domain.calibration import CalibrationDocument, CalibrationJoint
from momo.domain.enums import (
    CalibrationOperatingMode,
    ControlMode,
    HardwareAccessPolicy,
    KinematicsVerificationStatus,
    ProfileVerificationStatus,
    RobotVariant,
)
from momo.domain.kinematics.model import KinematicsModel
from momo.domain.profiles import canonical_robot_profile
from momo.domain.real_hardware import (
    ExplicitServoDevice,
    FieldAcceptanceStatus,
    HardwareDependencyState,
    RealHardwareContext,
)
from momo.domain.robot import RobotProfile
from momo.settings import repository_root
from tests.stage3_helpers import FakeClock


def real_profile() -> RobotProfile:
    data = canonical_robot_profile(RobotVariant.V2).model_dump(mode="python")
    data.update(
        {
            "template": False,
            "verification_status": ProfileVerificationStatus.VERIFIED_FOR_REAL,
            "source": "synthetic-stage8-test",
            "source_revision": "synthetic-only",
        }
    )
    return RobotProfile.model_validate(data)


def real_calibration(profile: RobotProfile) -> CalibrationDocument:
    return CalibrationDocument(
        robot_variant=profile.variant,
        profile_fingerprint=profile.fingerprint,
        template=False,
        notes="Synthetic Stage 8 test calibration; never field data.",
        joints=[
            CalibrationJoint(
                joint_id=definition.joint_id,
                servo_id=cast(int, definition.servo_id),
                operating_mode=CalibrationOperatingMode.MULTI_TURN,
                direction=1,
                home_present_raw=0,
                phase=0,
                raw_bounds=(-30719, 30719),
            )
            for definition in profile.joint_definitions
        ],
    )


def real_kinematics() -> KinematicsModel:
    source = FileKinematicsModelRepository(repository_root() / "kinematics_models").get(
        RobotVariant.V2
    )
    data = source.model_dump(mode="python")
    data["verification_status"] = KinematicsVerificationStatus.VERIFIED_FOR_REAL
    return KinematicsModel.model_validate(data)


def real_context(**updates: Any) -> RealHardwareContext:
    profile = real_profile()
    calibration = real_calibration(profile)
    kinematics = real_kinematics()
    device = ExplicitServoDevice(
        serial_port="/dev/fake-stage8-never-opened",
        protocol="SCS",
        servo_ids=tuple(cast(int, definition.servo_id) for definition in profile.joint_definitions),
    )
    values: dict[str, Any] = {
        "control_mode": ControlMode.REAL,
        "hardware_access_policy": HardwareAccessPolicy.FULL,
        "real_motion_enabled": True,
        "startup_hardware_enabled": True,
        "explicit_local_config": True,
        "robot_id": "primary",
        "profile": profile,
        "calibration": calibration,
        "kinematics": kinematics,
        "expected_kinematics_fingerprint": kinematics.fingerprint,
        "field_acceptance_status": FieldAcceptanceStatus.PASSED,
        "dependency_state": HardwareDependencyState.AVAILABLE,
        "dependency_adapter_id": "fake-servo-bus",
        "device": device,
    }
    values.update(updates)
    return RealHardwareContext.model_validate(values)


def fake_bus(context: RealHardwareContext, **updates: Any) -> FakeServoBus:
    device = context.device
    calibration = context.calibration
    assert device is not None and calibration is not None
    modes = {joint.servo_id: joint.operating_mode.value for joint in calibration.joints}
    values: dict[str, Any] = {
        "present_positions": {servo_id: 0 for servo_id in device.servo_ids},
        "operating_modes": modes,
        "torque_states": {servo_id: False for servo_id in device.servo_ids},
    }
    values.update(updates)
    return FakeServoBus(**values)


def device_service(
    context: RealHardwareContext,
    *,
    bus: FakeServoBus | None = None,
    clock: FakeClock | None = None,
) -> tuple[DeviceDiagnosticsService, FakeClock, FakeServoBusFactory]:
    resolved_clock = clock or FakeClock()
    authorization = RealHardwareAuthorization()
    sessions = OperatorSessionService(resolved_clock, authorization, ttl_s=60.0)
    resolved_bus = bus or fake_bus(context)
    factory = FakeServoBusFactory(resolved_bus)
    return (
        DeviceDiagnosticsService(
            context=context,
            authorization=authorization,
            sessions=sessions,
            bus_factory=factory,
            clock=resolved_clock,
        ),
        resolved_clock,
        factory,
    )
