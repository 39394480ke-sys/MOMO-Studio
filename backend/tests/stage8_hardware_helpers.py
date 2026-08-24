"""Synthetic Stage 8 hardware authorization fixtures; never real device data."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, NoReturn, cast

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
    FieldAcceptanceEvidence,
    FieldAcceptanceStatus,
    HardwareDependencyState,
    RealHardwareContext,
    calibration_fingerprint,
    explicit_device_fingerprint,
)
from momo.domain.robot import RobotProfile
from momo.settings import repository_root
from tests.stage3_helpers import FakeClock


def real_profile(variant: RobotVariant = RobotVariant.V2) -> RobotProfile:
    data = canonical_robot_profile(variant).model_dump(mode="python")
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
    context = RealHardwareContext.model_validate(values)
    if (
        "field_acceptance_evidence" not in updates
        and context.field_acceptance_status is FieldAcceptanceStatus.PASSED
        and context.profile is not None
        and context.calibration is not None
        and context.device is not None
    ):
        evidence = FieldAcceptanceEvidence(
            robot_variant=context.profile.variant,
            profile_fingerprint=context.profile.fingerprint,
            calibration_fingerprint=calibration_fingerprint(context.calibration),
            kinematics_fingerprint=(
                context.kinematics.fingerprint if context.kinematics is not None else None
            ),
            device_fingerprint=explicit_device_fingerprint(context.device),
            checklist_version=context.field_acceptance_checklist_version,
            accepted_at=datetime(2026, 1, 1, tzinfo=UTC),
            accepted_by="synthetic-stage8-test",
        )
        context = context.model_copy(update={"field_acceptance_evidence": evidence})
    return context


def commissioning_context(**updates: Any) -> RealHardwareContext:
    """Fresh or recalibration context whose only hardware authority is read-only."""

    context = real_context()
    kinematics = context.kinematics
    assert kinematics is not None
    provisional = kinematics.model_copy(
        update={"verification_status": KinematicsVerificationStatus.PROVISIONAL_DRY_RUN}
    )
    values: dict[str, Any] = {
        "hardware_access_policy": HardwareAccessPolicy.READ_ONLY,
        "real_motion_enabled": False,
        "calibration": None,
        "kinematics": provisional,
        "expected_kinematics_fingerprint": provisional.fingerprint,
        "field_acceptance_status": FieldAcceptanceStatus.PENDING,
        "field_acceptance_evidence": None,
    }
    values.update(updates)
    return RealHardwareContext.model_validate(context.model_copy(update=values).model_dump())


def recalibration_context(**updates: Any) -> RealHardwareContext:
    """Read-only commissioning context with an existing synthetic calibration."""

    context = real_context()
    assert context.calibration is not None
    values: dict[str, Any] = {"calibration": context.calibration}
    values.update(updates)
    return commissioning_context(**values)


def _fake_bus_values(context: RealHardwareContext, **updates: Any) -> dict[str, Any]:
    device = context.device
    profile = context.profile
    calibration = context.calibration
    assert device is not None and profile is not None
    modes = (
        {joint.servo_id: joint.operating_mode.value for joint in calibration.joints}
        if calibration is not None
        else {
            cast(int, definition.servo_id): definition.operating_mode.value
            for definition in profile.joint_definitions
        }
    )
    values: dict[str, Any] = {
        "present_positions": {servo_id: 0 for servo_id in device.servo_ids},
        "operating_modes": modes,
        "torque_states": {servo_id: False for servo_id in device.servo_ids},
    }
    values.update(updates)
    return values


def fake_bus(context: RealHardwareContext, **updates: Any) -> FakeServoBus:
    return FakeServoBus(**_fake_bus_values(context, **updates))


class WriteBombServoBus(FakeServoBus):
    """Fake read bus whose bounded hardware-write surface always explodes."""

    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
        self.write_attempts: list[str] = []

    async def write_goal_positions(
        self,
        goal_positions: Mapping[int, int],
    ) -> NoReturn:
        del goal_positions
        self.write_attempts.append("write_goal_positions")
        raise AssertionError("write path must never be reachable")

    async def stop_or_hold(self, servo_ids: tuple[int, ...]) -> NoReturn:
        del servo_ids
        self.write_attempts.append("stop_or_hold")
        raise AssertionError("write path must never be reachable")


def write_bomb_bus(context: RealHardwareContext, **updates: Any) -> WriteBombServoBus:
    return WriteBombServoBus(**_fake_bus_values(context, **updates))


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
