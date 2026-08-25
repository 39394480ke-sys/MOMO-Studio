"""Synthetic Kinematics verification workflow; no hardware or camera access."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import pytest

from momo.adapters.kinematics.model_repository import FileKinematicsModelRepository
from momo.adapters.kinematics.serial_chain import SerialChainKinematics
from momo.adapters.storage.file_kinematics_verification_repository import (
    FileKinematicsVerificationEvidenceRepository,
)
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.kinematics_verification_service import (
    KinematicsVerificationDraftError,
    KinematicsVerificationPrerequisiteError,
    KinematicsVerificationService,
    KinematicsVerificationThresholdError,
)
from momo.application.services.operator_session_service import OperatorSessionTokenError
from momo.domain.commissioning import (
    KinematicsEvidenceState,
    KinematicsVerificationEvidence,
)
from momo.domain.real_hardware import (
    REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
    OperatorSessionPurpose,
    calibration_fingerprint,
    explicit_device_fingerprint,
)
from momo.domain.robot import JointState
from momo.ports.kinematics_joint_snapshot import KinematicsJointStateSnapshot
from momo.settings import repository_root
from tests.stage3_helpers import FakeClock
from tests.stage8_hardware_helpers import device_service, real_context


class FakeJointStateSnapshotProvider:
    """Test-only server snapshot source; it performs no hardware access."""

    def __init__(self, context: object, clock: FakeClock) -> None:
        self.context = context
        self.clock = clock
        self.session_id: UUID | None = None
        self.joint_state: JointState | None = None
        self.state_sequence = 0

    def prepare(
        self,
        *,
        session_id: UUID,
        joint_state: JointState,
        state_sequence: int,
    ) -> None:
        self.session_id = session_id
        self.joint_state = joint_state
        self.state_sequence = state_sequence

    async def capture(self) -> KinematicsJointStateSnapshot:
        from momo.domain.real_hardware import RealHardwareContext

        assert isinstance(self.context, RealHardwareContext)
        assert self.context.profile is not None
        assert self.context.calibration is not None
        assert self.context.device is not None
        assert self.session_id is not None
        assert self.joint_state is not None
        return KinematicsJointStateSnapshot(
            robot_unit_id=self.context.robot_unit_id,
            profile_fingerprint=self.context.profile.fingerprint,
            calibration_fingerprint=calibration_fingerprint(self.context.calibration),
            device_fingerprint=explicit_device_fingerprint(self.context.device),
            operator_session_id=self.session_id,
            joint_state=self.joint_state,
            state_sequence=self.state_sequence,
            captured_at=self.clock.now(),
        )


class BarrierKinematicsRepository:
    """Persist audit data, then pause before commit can publish authority."""

    def __init__(self) -> None:
        self.values: dict[UUID, KinematicsVerificationEvidence] = {}
        self.saved = asyncio.Event()
        self.release = asyncio.Event()

    async def get(self, evidence_id: UUID) -> KinematicsVerificationEvidence | None:
        return self.values.get(evidence_id)

    async def list_evidence(self) -> tuple[KinematicsVerificationEvidence, ...]:
        return tuple(self.values.values())

    async def save(self, evidence: KinematicsVerificationEvidence) -> None:
        self.values[evidence.id] = evidence
        self.saved.set()
        await self.release.wait()


def test_multiple_measured_points_commit_and_bind_current_unit(tmp_path: Path) -> None:
    async def scenario() -> None:
        context = real_context()
        device, clock, _ = device_service(context)
        kinematics = KinematicsService(
            FileKinematicsModelRepository(repository_root() / "kinematics_models"),
            SerialChainKinematics(),
        )
        repository = FileKinematicsVerificationEvidenceRepository(tmp_path, clock)
        snapshot_provider = FakeJointStateSnapshotProvider(context, clock)
        service = KinematicsVerificationService(
            device=device,
            kinematics=kinematics,
            repository=repository,
            clock=clock,
            joint_state_snapshot_provider=snapshot_provider,
        )
        issued = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.REAL_MOTION,
            confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
            operator_id="synthetic-kinematics-reviewer",
        )
        token = issued.session_token.get_secret_value()
        draft = await service.start_draft(token)
        assert context.profile is not None
        units = {
            definition.joint_id: definition.domain_unit
            for definition in context.profile.joint_definitions
        }
        for index in range(3):
            state = JointState(
                positions={
                    joint_id: (float(index * 10) if joint_id == "j10" else 0.0)
                    for joint_id in context.profile.enabled_joints
                },
                units=units,
            )
            predicted = await kinematics.forward(
                context.profile,
                state,
                state_sequence=index,
            )
            snapshot_provider.prepare(
                session_id=issued.evidence.session_id,
                joint_state=state,
                state_sequence=index,
            )
            draft = await service.add_measurement(
                token,
                draft.draft_id,
                label=f"measured-point-{index + 1}",
                measured_tcp=predicted.tcp_pose,
            )
        evidence = await service.commit(token, draft.draft_id)

        assert evidence.robot_unit_id == context.robot_unit_id
        assert len(evidence.test_points) == 3
        assert all(point.position_error_mm == 0 for point in evidence.test_points)
        assert tuple(point.joint_state_sequence for point in evidence.test_points) == (0, 1, 2)
        assert all(
            point.snapshot_session_id == issued.evidence.session_id
            for point in evidence.test_points
        )
        assert (await repository.get(evidence.id)) == evidence
        assert service.status().state is KinematicsEvidenceState.VALID

    asyncio.run(scenario())


def test_insufficient_or_over_threshold_points_fail_and_context_change_stales_draft(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        context = real_context()
        device, clock, _ = device_service(context)
        kinematics = KinematicsService(
            FileKinematicsModelRepository(repository_root() / "kinematics_models"),
            SerialChainKinematics(),
        )
        repository = FileKinematicsVerificationEvidenceRepository(tmp_path, clock)
        snapshot_provider = FakeJointStateSnapshotProvider(context, clock)
        service = KinematicsVerificationService(
            device=device,
            kinematics=kinematics,
            repository=repository,
            clock=clock,
            joint_state_snapshot_provider=snapshot_provider,
        )
        issued = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.REAL_MOTION,
            confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        token = issued.session_token.get_secret_value()
        draft = await service.start_draft(token)
        with pytest.raises(KinematicsVerificationThresholdError):
            await service.commit(token, draft.draft_id)

        assert context.profile is not None
        units = {
            definition.joint_id: definition.domain_unit
            for definition in context.profile.joint_definitions
        }
        for index in range(3):
            state = JointState(
                positions={
                    joint_id: (float(index * 10) if joint_id == "j10" else 0.0)
                    for joint_id in context.profile.enabled_joints
                },
                units=units,
            )
            predicted = await kinematics.forward(
                context.profile,
                state,
                state_sequence=index,
            )
            measured_position = predicted.tcp_pose.position_mm.model_copy(
                update={"x": predicted.tcp_pose.position_mm.x + 100.0}
            )
            snapshot_provider.prepare(
                session_id=issued.evidence.session_id,
                joint_state=state,
                state_sequence=index,
            )
            draft = await service.add_measurement(
                token,
                draft.draft_id,
                label=f"over-threshold-point-{index + 1}",
                measured_tcp=predicted.tcp_pose.model_copy(
                    update={"position_mm": measured_position}
                ),
            )
        with pytest.raises(KinematicsVerificationThresholdError):
            await service.commit(token, draft.draft_id)
        assert await repository.list_evidence() == ()

        device.context = device.context.model_copy(update={"robot_unit_id": "MOMO-V2-UNIT-CHANGED"})
        with pytest.raises(OperatorSessionTokenError):
            await service.commit(token, draft.draft_id)

        # Direct draft lookup also fails closed if called with a mismatched session.
        with pytest.raises(KinematicsVerificationDraftError):
            service._require_current_draft(draft.draft_id, issued.evidence)

    asyncio.run(scenario())


def test_missing_server_owned_snapshot_provider_fails_closed(tmp_path: Path) -> None:
    async def scenario() -> None:
        context = real_context()
        device, clock, _ = device_service(context)
        kinematics = KinematicsService(
            FileKinematicsModelRepository(repository_root() / "kinematics_models"),
            SerialChainKinematics(),
        )
        service = KinematicsVerificationService(
            device=device,
            kinematics=kinematics,
            repository=FileKinematicsVerificationEvidenceRepository(tmp_path, clock),
            clock=clock,
        )
        issued = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.REAL_MOTION,
            confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        draft = await service.start_draft(issued.session_token.get_secret_value())
        assert context.profile is not None
        units = {
            definition.joint_id: definition.domain_unit
            for definition in context.profile.joint_definitions
        }
        state = JointState(
            positions={joint_id: 0.0 for joint_id in context.profile.enabled_joints},
            units=units,
        )
        predicted = await kinematics.forward(context.profile, state, state_sequence=0)

        with pytest.raises(KinematicsVerificationPrerequisiteError):
            await service.add_measurement(
                issued.session_token.get_secret_value(),
                draft.draft_id,
                label="client-cannot-supply-joint-state",
                measured_tcp=predicted.tcp_pose,
            )

    asyncio.run(scenario())


def test_session_revoked_during_save_cannot_publish_kinematics_authority() -> None:
    async def scenario() -> None:
        context = real_context().model_copy(update={"kinematics_verification_evidence": None})
        device, clock, _ = device_service(context)
        kinematics = KinematicsService(
            FileKinematicsModelRepository(repository_root() / "kinematics_models"),
            SerialChainKinematics(),
        )
        repository = BarrierKinematicsRepository()
        snapshot_provider = FakeJointStateSnapshotProvider(context, clock)
        service = KinematicsVerificationService(
            device=device,
            kinematics=kinematics,
            repository=repository,
            clock=clock,
            joint_state_snapshot_provider=snapshot_provider,
        )
        issued = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.REAL_MOTION,
            confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        token = issued.session_token.get_secret_value()
        draft = await service.start_draft(token)
        assert context.profile is not None
        units = {
            definition.joint_id: definition.domain_unit
            for definition in context.profile.joint_definitions
        }
        for index in range(3):
            state = JointState(
                positions={
                    joint_id: (float(index * 10) if joint_id == "j10" else 0.0)
                    for joint_id in context.profile.enabled_joints
                },
                units=units,
            )
            predicted = await kinematics.forward(
                context.profile,
                state,
                state_sequence=index,
            )
            snapshot_provider.prepare(
                session_id=issued.evidence.session_id,
                joint_state=state,
                state_sequence=index,
            )
            draft = await service.add_measurement(
                token,
                draft.draft_id,
                label=f"revocation-point-{index + 1}",
                measured_tcp=predicted.tcp_pose,
            )

        committing = asyncio.create_task(service.commit(token, draft.draft_id))
        await repository.saved.wait()
        await device.revoke_operator_session(token)
        repository.release.set()

        with pytest.raises(OperatorSessionTokenError):
            await committing
        assert len(repository.values) == 1
        assert device.context.kinematics_verification_evidence is None

    asyncio.run(scenario())
