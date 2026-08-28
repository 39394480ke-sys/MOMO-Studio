"""Synthetic Stage 8 hardware authorization fixtures; never real device data."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, NoReturn, cast
from uuid import UUID

from momo.adapters.hardware.fake_servo_bus import FakeServoBus, FakeServoBusFactory
from momo.adapters.kinematics.model_repository import FileKinematicsModelRepository
from momo.application.services.device_diagnostics_service import DeviceDiagnosticsService
from momo.application.services.operator_session_service import OperatorSessionService
from momo.application.services.real_hardware_authorization import RealHardwareAuthorization
from momo.domain.calibration import CalibrationDocument, CalibrationJoint
from momo.domain.commissioning import (
    FieldAcceptanceBundle,
    FieldAcceptanceCapability,
    FieldAcceptanceEvidence,
    KinematicsVerificationEvidence,
    KinematicsVerificationPoint,
    KinematicsVerificationThresholds,
    PhysicalStopVerification,
    PreMotionChecksSnapshot,
    PreMotionDiagnosticRecord,
    ValidatedFieldAcceptanceBundle,
)
from momo.domain.enums import (
    CalibrationOperatingMode,
    ControlMode,
    HardwareAccessPolicy,
    KinematicsVerificationStatus,
    ProfileVerificationStatus,
    RobotVariant,
)
from momo.domain.hardware_mapping import goal_raw_to_logical
from momo.domain.kinematics.model import KinematicsModel
from momo.domain.pose import QuaternionXYZW, TcpPose, Vector3
from momo.domain.profiles import canonical_robot_profile
from momo.domain.real_hardware import (
    ExplicitServoDevice,
    FieldAcceptanceStatus,
    HardwareDependencyState,
    RealHardwareContext,
    calibration_fingerprint,
    explicit_device_fingerprint,
)
from momo.domain.robot import JointState, RobotProfile
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
        robot_unit_id="MOMO-V2-UNIT-SYNTHETIC",
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
        robot_unit_id="MOMO-V2-UNIT-SYNTHETIC",
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
        "robot_unit_id": "MOMO-V2-UNIT-SYNTHETIC",
        "software_commit": "synthetic-test-commit",
        "robot_id": "primary",
        "profile": profile,
        "calibration": calibration,
        "kinematics": kinematics,
        "expected_kinematics_fingerprint": kinematics.fingerprint,
        "field_acceptance_status": FieldAcceptanceStatus.PASSED,
        "physical_stop_verification": PhysicalStopVerification.VERIFIED_FOR_UNIT,
        "dependency_state": HardwareDependencyState.AVAILABLE,
        "dependency_adapter_id": "fake-servo-bus",
        "device": device,
    }
    values.update(updates)
    context = RealHardwareContext.model_validate(values)
    if (
        "field_acceptance_evidence" not in updates
        and "field_acceptance_bundle" not in updates
        and context.field_acceptance_status is FieldAcceptanceStatus.PASSED
        and context.profile is not None
        and context.calibration is not None
        and context.device is not None
        and all(
            joint.complete and joint.raw_bounds is not None for joint in context.calibration.joints
        )
    ):
        accepted_at = datetime(2026, 1, 1, tzinfo=UTC)
        evidence_ids = {
            capability: (f"00000000-0000-4000-8000-00000000000{index}",)
            for index, capability in enumerate(
                (
                    FieldAcceptanceCapability.JOINT_MOTION,
                    FieldAcceptanceCapability.CARTESIAN,
                    FieldAcceptanceCapability.PLAYBACK,
                    FieldAcceptanceCapability.VISION_FOLLOW,
                ),
                start=1,
            )
        }
        records = tuple(
            FieldAcceptanceEvidence.for_capability(
                context=context,
                capability=capability,
                checklist_version=context.field_acceptance_checklist_version,
                test_evidence_ids=evidence_ids.get(capability, ()),
                accepted_at=accepted_at,
                accepted_by="synthetic-stage8-test",
                software_commit="synthetic-test-commit",
                pre_motion_snapshot=(
                    synthetic_pre_motion_snapshot(context, accepted_at)
                    if capability is FieldAcceptanceCapability.PRE_MOTION_CHECKS
                    else None
                ),
            )
            for capability in FieldAcceptanceCapability
        )
        kinematics_evidence = None
        if context.kinematics is not None:
            state_units = {
                definition.joint_id: definition.domain_unit
                for definition in context.profile.joint_definitions
            }
            tcp = TcpPose(
                frame="base",
                position_mm=Vector3(x=0.0, y=0.0, z=0.0),
                orientation_quaternion_xyzw=QuaternionXYZW(x=0.0, y=0.0, z=0.0, w=1.0),
            )
            kinematics_evidence = KinematicsVerificationEvidence(
                robot_unit_id=context.robot_unit_id,
                variant=context.profile.variant,
                profile_fingerprint=context.profile.fingerprint,
                calibration_fingerprint=calibration_fingerprint(context.calibration),
                device_fingerprint=explicit_device_fingerprint(context.device),
                kinematics_fingerprint=context.kinematics.fingerprint,
                kinematics_model_schema_version=context.kinematics.schema_version,
                verification_checklist_version=(context.kinematics_verification_checklist_version),
                test_points=tuple(
                    KinematicsVerificationPoint(
                        label=f"synthetic-point-{index}",
                        joint_state=JointState(
                            positions={
                                joint_id: (
                                    float((index - 1) * 10)
                                    if joint_id == context.profile.enabled_joints[0]
                                    else 0.0
                                )
                                for joint_id in context.profile.enabled_joints
                            },
                            units=state_units,
                        ),
                        joint_state_sequence=index,
                        joint_state_captured_at=accepted_at,
                        snapshot_session_id=UUID("00000000-0000-4000-8000-000000000099"),
                        predicted_tcp=tcp,
                        measured_tcp=tcp,
                        position_error_mm=0.0,
                        orientation_error_deg=0.0,
                        measured_at=accepted_at,
                    )
                    for index in range(1, 4)
                ),
                thresholds=KinematicsVerificationThresholds(),
                accepted_at=accepted_at,
                accepted_by="synthetic-stage8-test",
                software_commit="synthetic-test-commit",
            )
        joint_evidence = next(
            item for item in records if item.capability is FieldAcceptanceCapability.JOINT_MOTION
        )
        context = context.model_copy(
            update={
                "field_acceptance_evidence": joint_evidence,
                "field_acceptance_bundle": ValidatedFieldAcceptanceBundle(records=records),
                "kinematics_verification_evidence": kinematics_evidence,
            }
        )
    return context


def synthetic_pre_motion_snapshot(
    context: RealHardwareContext,
    captured_at: datetime,
) -> PreMotionChecksSnapshot:
    """Build typed Fake-only read-only evidence for authorization tests."""

    profile = context.profile
    calibration = context.calibration
    assert profile is not None and calibration is not None
    records: list[PreMotionDiagnosticRecord] = []
    for joint_id in profile.enabled_joints:
        joint = calibration.joints_by_id[joint_id]
        assert joint.home_present_raw is not None and joint.raw_bounds is not None
        records.append(
            PreMotionDiagnosticRecord(
                joint_id=joint_id,
                servo_id=joint.servo_id,
                ping_responded=True,
                operating_mode=joint.operating_mode.value,
                present_raw=joint.home_present_raw,
                logical_value=goal_raw_to_logical(
                    joint_id,
                    joint.home_present_raw,
                    profile,
                    joint,
                ),
                raw_bounds=joint.raw_bounds,
                torque_enabled=False,
            )
        )
    return PreMotionChecksSnapshot(
        operator_session_id=UUID("00000000-0000-4000-8000-000000000098"),
        captured_at=captured_at,
        records=tuple(records),
    )


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
        "field_acceptance_bundle": FieldAcceptanceBundle(),
        "kinematics_verification_evidence": None,
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
