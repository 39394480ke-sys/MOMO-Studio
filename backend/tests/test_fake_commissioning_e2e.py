"""Full synthetic unit commissioning path; no physical adapter is composed."""

from __future__ import annotations

import asyncio
from pathlib import Path

from momo.adapters.hardware.fake_commissioning_motion_bus import (
    FakeCommissioningMotionBus,
)
from momo.adapters.storage.file_calibration_workflow_repository import (
    FileCalibrationWorkflowRepository,
)
from momo.adapters.storage.file_commissioning_evidence_repository import (
    FileCommissioningTestEvidenceRepository,
)
from momo.adapters.storage.file_field_acceptance_repository import (
    FileFieldAcceptanceEvidenceRepository,
)
from momo.application.services.calibration_workflow_coordinator import (
    CalibrationWorkflowCoordinator,
)
from momo.application.services.calibration_workflow_service import (
    CALIBRATION_JOINT_CONFIRMATION,
    SAVE_CALIBRATION_CONFIRMATION,
)
from momo.application.services.commissioning_motion_test_service import (
    CommissioningMotionTestService,
)
from momo.application.services.field_acceptance_service import (
    FieldAcceptanceService,
    validated_field_acceptance_bundle,
)
from momo.domain.calibration_workflow import CalibrationWorkflowSource
from momo.domain.commissioning import (
    CommissioningTestResult,
    FieldAcceptanceBundle,
    FieldAcceptanceCapability,
    PhysicalStopVerification,
)
from momo.domain.enums import HardwareAccessPolicy
from momo.domain.real_hardware import (
    REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
    REQUIRED_COMMISSIONING_MOTION_CONFIRMATION_TEXT,
    FieldAcceptanceStatus,
    OperatorSessionPurpose,
    RealHardwareBlocker,
    RealStopResult,
)
from tests.stage8_hardware_helpers import commissioning_context, device_service


def test_fresh_fake_unit_completes_all_joint_evidence_but_not_physical_acceptance(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        configured = commissioning_context(
            hardware_access_policy=HardwareAccessPolicy.READ_ONLY,
        )
        configured_device = configured.device
        assert configured_device is not None
        unassigned = configured.model_copy(update={"robot_unit_id": "", "device": None})
        assert unassigned.robot_unit_id == "" and unassigned.calibration is None
        # Simulate the explicit untracked local-config assignment. No port-derived,
        # Servo-ID-derived, or hostname-derived identity is used.
        context = unassigned.model_copy(
            update={
                "robot_unit_id": configured.robot_unit_id,
                "device": configured_device,
                "field_acceptance_status": FieldAcceptanceStatus.PENDING,
                "field_acceptance_evidence": None,
                "field_acceptance_bundle": FieldAcceptanceBundle(),
                "kinematics_verification_evidence": None,
                "physical_stop_verification": PhysicalStopVerification.PENDING,
            }
        )
        assert context.profile is not None
        assert context.device is not None
        assert context.robot_unit_id == "MOMO-V2-UNIT-SYNTHETIC"
        assert context.calibration is None

        device, clock, read_only_factory = device_service(context)
        field_repository = FileFieldAcceptanceEvidenceRepository(
            tmp_path / "field-acceptance",
            clock,
        )
        commissioning_repository = FileCommissioningTestEvidenceRepository(
            tmp_path / "commissioning-tests",
            clock,
        )
        acceptance = FieldAcceptanceService(
            device=device,
            repository=field_repository,
            commissioning_repository=commissioning_repository,
            clock=clock,
        )
        calibration_repository = FileCalibrationWorkflowRepository(tmp_path / "calibration")
        calibration = CalibrationWorkflowCoordinator(
            device=device,
            repository=calibration_repository,
            clock=clock,
        )

        read_only = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
            operator_id="fake-read-only-operator",
        )
        read_only_token = read_only.session_token.get_secret_value()
        diagnostics = await device.connect(read_only_token)
        assert diagnostics.connected is True
        assert len(diagnostics.records) == len(context.profile.enabled_joints)
        assert all(record.logical_value is None for record in diagnostics.records)

        calibration_status = await calibration.start(
            read_only_token,
            source=CalibrationWorkflowSource.EXISTING_REAL,
        )
        assert calibration_status.base_revision is None
        for definition in context.profile.joint_definitions:
            assert definition.raw_bounds is not None
            calibration_status = await calibration.read_selected_joint(
                read_only_token,
                calibration_status.session_id,
                definition.joint_id,
            )
            preview = await calibration.preview_joint(
                read_only_token,
                calibration_status.session_id,
                definition.joint_id,
                logical_value=0.0,
                direction=1,
                phase=0,
                raw_bounds=definition.raw_bounds,
            )
            calibration_status = await calibration.confirm_joint(
                read_only_token,
                calibration_status.session_id,
                definition.joint_id,
                preview_fingerprint=preview.preview_fingerprint,
                confirmation=CALIBRATION_JOINT_CONFIRMATION,
            )
        assert calibration_status.save_preview is not None
        revision_one = await calibration.complete(
            read_only_token,
            calibration_status.session_id,
            proposed_calibration_fingerprint=(
                calibration_status.save_preview.proposed_calibration_fingerprint
            ),
            confirmation=SAVE_CALIBRATION_CONFIRMATION,
        )
        assert revision_one.revision == 1
        assert revision_one.calibration.robot_unit_id == context.robot_unit_id
        assert device.context.calibration == revision_one.calibration
        assert device.connected is False

        read_only = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
            operator_id="fake-pre-motion-operator",
        )
        read_only_token = read_only.session_token.get_secret_value()
        diagnostics = await device.connect(read_only_token)
        assert all(record.logical_value is not None for record in diagnostics.records)
        pre_motion = await acceptance.complete_pre_motion_checks(
            read_only_token,
            checklist_version=context.field_acceptance_checklist_version,
        )
        assert pre_motion.pre_motion_checks_complete is True
        assert device.connected is False
        assert not any(
            event[0] in {"write_goal_positions", "stop_or_hold", "scan", "home"}
            for event in read_only_factory.bus.events
        )

        # This explicit local configuration transition is not a session upgrade:
        # the read-only token was already invalidated by the accepted checklist.
        persisted_pre_motion = field_repository.list_evidence()
        restart_context = device.context.model_copy(
            update={
                "hardware_access_policy": HardwareAccessPolicy.FULL,
                "real_motion_enabled": True,
                "commissioning_motion_test_enabled": True,
                "field_acceptance_evidence": None,
                "field_acceptance_bundle": FieldAcceptanceBundle(records=persisted_pre_motion),
            }
        )
        resolved_after_restart = validated_field_acceptance_bundle(
            restart_context,
            persisted_pre_motion,
            (),
        )
        assert resolved_after_restart.valid_capabilities(restart_context) == frozenset(
            {FieldAcceptanceCapability.PRE_MOTION_CHECKS}
        )
        device.context = restart_context.model_copy(
            update={
                "field_acceptance_evidence": persisted_pre_motion[0],
                "field_acceptance_bundle": resolved_after_restart,
            }
        )

        motion_session = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.COMMISSIONING_MOTION_TEST,
            confirmation_text=REQUIRED_COMMISSIONING_MOTION_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
            workspace_clear_confirmed=True,
            operator_id="fake-motion-test-operator",
        )
        motion_token = motion_session.session_token.get_secret_value()
        bus = FakeCommissioningMotionBus(
            allowed_servo_ids=context.device.servo_ids,
            session_id=motion_session.evidence.session_id,
            present_positions={servo_id: 0 for servo_id in context.device.servo_ids},
            clock=clock,
            write_enabled=True,
            stop_result=RealStopResult.HOLD_REQUESTED,
        )
        motion = CommissioningMotionTestService(
            context=lambda: device.context,
            sessions=device.sessions,
            bus=bus,
            allowed_servo_ids=context.device.servo_ids,
            repository=commissioning_repository,
            clock=clock,
            software_commit=context.software_commit,
        )
        await motion.start_session(motion_token)

        for joint_id in context.profile.enabled_joints:
            definition = context.profile.definitions_by_id[joint_id]
            delta = 0.25 if definition.domain_unit.value == "mm" else 0.5
            speed = 0.5 if definition.domain_unit.value == "mm" else 1.0
            acceleration = 2.0
            for direction in (1.0, -1.0):
                await motion.arm(motion_token, joint_id=joint_id)
                evidence = await motion.run_relative_test(
                    motion_token,
                    joint_id=joint_id,
                    signed_delta=direction * delta,
                    requested_speed=speed,
                    requested_acceleration=acceleration,
                    command_duration_s=2.0,
                    request_id=f"fake-e2e-{joint_id}-{direction:+.0f}",
                )
                assert evidence.result is CommissioningTestResult.PASSED

        evidence_records = await commissioning_repository.list_evidence()
        assert len(evidence_records) == len(context.profile.enabled_joints) * 2
        progress = await acceptance.accept_joint_motion(
            motion_token,
            checklist_version=context.field_acceptance_checklist_version,
        )
        assert progress.joint_motion_tests_complete is True
        assert progress.joint_motion_accepted is True
        assert FieldAcceptanceCapability.JOINT_MOTION in progress.valid_capabilities
        assert progress.physical_stop_verification is PhysicalStopVerification.PENDING
        assert progress.full_acceptance_complete is False

        readiness = await device.readiness()
        assert readiness.capabilities.real_joint_motion_ready is False
        assert RealHardwareBlocker.PHYSICAL_STOP_NOT_VERIFIED in readiness.blocking_reasons
        assert readiness.capabilities.real_cartesian_motion_ready is False
        assert RealHardwareBlocker.KINEMATICS_VERIFICATION_PENDING in readiness.blocking_reasons
        assert device.context.kinematics_verification_evidence is None
        await motion.shutdown()

    asyncio.run(scenario())
