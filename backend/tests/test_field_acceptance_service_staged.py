"""Staged field acceptance consumes only synthetic, persisted commissioning facts."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from momo.adapters.storage.file_commissioning_evidence_repository import (
    FileCommissioningTestEvidenceRepository,
)
from momo.adapters.storage.file_field_acceptance_repository import (
    FileFieldAcceptanceEvidenceRepository,
)
from momo.application.services.field_acceptance_service import (
    FieldAcceptanceManualPassForbiddenError,
    FieldAcceptancePrerequisiteError,
    FieldAcceptanceProgressState,
    FieldAcceptanceService,
    JointTestEvidenceIncompleteError,
    validated_field_acceptance_bundle,
)
from momo.application.services.operator_session_service import OperatorSessionTokenError
from momo.domain.commissioning import (
    CommissioningDirection,
    CommissioningSafetyEnvelope,
    CommissioningTestEvidence,
    CommissioningTestResult,
    FieldAcceptanceBundle,
    FieldAcceptanceCapability,
    FieldAcceptanceEvidence,
    FieldAcceptanceEvidenceState,
    PhysicalStopVerification,
    PreparedCommissioningTestCommand,
    StopBehavior,
    ValidatedFieldAcceptanceBundle,
)
from momo.domain.enums import HardwareAccessPolicy
from momo.domain.hardware_mapping import goal_raw_to_logical, logical_to_goal_raw
from momo.domain.real_hardware import (
    REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
    REQUIRED_COMMISSIONING_MOTION_CONFIRMATION_TEXT,
    REQUIRED_FIELD_ACCEPTANCE_CONFIRMATION_TEXT,
    FieldAcceptanceStatus,
    OperatorSessionPurpose,
    RealHardwareAuthorizationPurpose,
    RealHardwareContext,
    calibration_fingerprint,
    explicit_device_fingerprint,
)
from tests.stage3_helpers import FakeClock
from tests.stage8_hardware_helpers import (
    device_service,
    fake_bus,
    real_context,
    synthetic_pre_motion_snapshot,
)


class BarrierFieldAcceptanceRepository:
    """Pause the synchronous save while the device publication guard is held."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.saved = asyncio.Event()
        self.release = threading.Event()
        self.values: dict[UUID, FieldAcceptanceEvidence] = {}

    def list_evidence(self) -> tuple[FieldAcceptanceEvidence, ...]:
        return tuple(self.values.values())

    def save(self, evidence: FieldAcceptanceEvidence) -> None:
        self.values[evidence.evidence_id] = evidence
        self.loop.call_soon_threadsafe(self.saved.set)
        if not self.release.wait(timeout=5.0):
            raise TimeoutError("field acceptance persistence barrier timed out")


def _unaccepted_context(*, read_only: bool = False) -> RealHardwareContext:
    return real_context(
        hardware_access_policy=(
            HardwareAccessPolicy.READ_ONLY if read_only else HardwareAccessPolicy.FULL
        ),
        real_motion_enabled=False,
        commissioning_motion_test_enabled=not read_only,
        field_acceptance_status=FieldAcceptanceStatus.PENDING,
        field_acceptance_evidence=None,
        field_acceptance_bundle=FieldAcceptanceBundle(),
        kinematics_verification_evidence=None,
        physical_stop_verification=PhysicalStopVerification.PENDING,
    )


def _pre_motion_context() -> RealHardwareContext:
    context = _unaccepted_context()
    pre_motion = FieldAcceptanceEvidence.for_capability(
        context=context,
        capability=FieldAcceptanceCapability.PRE_MOTION_CHECKS,
        checklist_version=context.field_acceptance_checklist_version,
        test_evidence_ids=(),
        accepted_at=FakeClock().now(),
        accepted_by="synthetic-pre-motion-operator",
        software_commit=context.software_commit,
        pre_motion_snapshot=synthetic_pre_motion_snapshot(context, FakeClock().now()),
    )
    return context.model_copy(
        update={
            "field_acceptance_evidence": pre_motion,
            "field_acceptance_bundle": ValidatedFieldAcceptanceBundle(records=(pre_motion,)),
        }
    )


def _joint_test_evidence(
    context: RealHardwareContext,
    joint_id: str,
    direction: CommissioningDirection,
    clock: FakeClock,
    *,
    stop_behavior: StopBehavior = StopBehavior.PHYSICAL_BEHAVIOR_PENDING,
    robot_unit_id: str | None = None,
) -> CommissioningTestEvidence:
    assert context.profile is not None
    assert context.calibration is not None
    assert context.device is not None
    definition = context.profile.definitions_by_id[joint_id]
    assert definition.servo_id is not None
    calibration_joint = context.calibration.joints_by_id[joint_id]
    magnitude = 0.25 if definition.domain_unit.value == "mm" else 0.5
    requested_delta = magnitude if direction is CommissioningDirection.POSITIVE else -magnitude
    # The V2 rail has a logical lower limit of zero, so exercise both directions
    # from a bounded interior point rather than fabricating a negative Home move.
    start_value = 10.0 if definition.domain_unit.value == "mm" else 0.0
    target_value = start_value + requested_delta
    start_raw = logical_to_goal_raw(
        joint_id,
        start_value,
        context.profile,
        calibration_joint,
    )
    target_raw = logical_to_goal_raw(
        joint_id,
        target_value,
        context.profile,
        calibration_joint,
    )
    final_value = goal_raw_to_logical(
        joint_id,
        target_raw,
        context.profile,
        calibration_joint,
    )
    session_id = uuid4()
    prepared_at = clock.now()
    prepared = PreparedCommissioningTestCommand(
        session_id=session_id,
        robot_unit_id=robot_unit_id or context.robot_unit_id,
        joint_id=joint_id,
        servo_id=definition.servo_id,
        unit=definition.domain_unit,
        start_value=start_value,
        requested_delta=requested_delta,
        target_value=target_value,
        start_raw=start_raw,
        target_raw=target_raw,
        requested_speed=0.5,
        requested_acceleration=0.5,
        command_duration_s=1.0,
        prepared_at=prepared_at,
        readback_fresh_until=prepared_at + timedelta(seconds=0.25),
        envelope=context.commissioning_safety_envelope,
    )
    return CommissioningTestEvidence(
        robot_unit_id=robot_unit_id or context.robot_unit_id,
        robot_variant=context.profile.variant,
        profile_fingerprint=context.profile.fingerprint,
        calibration_fingerprint=calibration_fingerprint(context.calibration),
        device_fingerprint=explicit_device_fingerprint(context.device),
        joint_id=joint_id,
        unit=definition.domain_unit,
        start_value=start_value,
        requested_delta=requested_delta,
        target_value=target_value,
        final_value=final_value,
        start_raw=start_raw,
        final_raw=target_raw,
        requested_speed=0.5,
        measured_or_observed_result="synthetic fresh bounded readback",
        direction_expected=direction,
        direction_observed=direction,
        divergence=abs(final_value - target_value),
        stop_behavior=stop_behavior,
        started_at=clock.now(),
        completed_at=clock.now(),
        software_commit=context.software_commit,
        operator_id="synthetic-motion-test-operator",
        request_id=f"{joint_id}-{direction.value}-{uuid4()}",
        session_id=session_id,
        prepared_target_raw=target_raw,
        prepared_command=prepared,
        result=CommissioningTestResult.PASSED,
    )


def test_manual_global_pass_is_forbidden_and_pre_motion_is_read_only_derived(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        context = _unaccepted_context(read_only=True)
        clock = FakeClock()
        device, _, bus_factory = device_service(context, clock=clock)
        repository = FileFieldAcceptanceEvidenceRepository(tmp_path, clock)
        service = FieldAcceptanceService(
            device=device,
            repository=repository,
            clock=clock,
        )
        issued = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
            operator_id="server-derived-operator",
        )
        token = issued.session_token.get_secret_value()
        await device.connect(token)

        with pytest.raises(FieldAcceptanceManualPassForbiddenError):
            await service.accept(
                token,
                checklist_version=context.field_acceptance_checklist_version,
                confirmation_text=REQUIRED_FIELD_ACCEPTANCE_CONFIRMATION_TEXT,
                accepted_by="client-cannot-authorize",
            )
        assert repository.list_evidence() == ()
        assert device.connected is True

        progress = await service.complete_pre_motion_checks(
            token,
            checklist_version=context.field_acceptance_checklist_version,
        )

        assert progress.state is FieldAcceptanceProgressState.PRE_MOTION_CHECKS_COMPLETE
        assert progress.pre_motion_checks_complete is True
        assert progress.joint_motion_accepted is False
        assert progress.full_acceptance_complete is False
        assert progress.physical_stop_verification is PhysicalStopVerification.PENDING
        assert device.connected is False
        assert (await device.sessions.status()).active is False
        with pytest.raises(OperatorSessionTokenError):
            await device.authorize_operator_purpose(
                token,
                purpose=RealHardwareAuthorizationPurpose.DIAGNOSTICS,
            )
        records = repository.list_evidence()
        assert len(records) == 1
        assert records[0].schema_version == 2
        assert records[0].capability is FieldAcceptanceCapability.PRE_MOTION_CHECKS
        assert records[0].accepted_by == "server-derived-operator"
        assert records[0].test_evidence_ids == ()
        persisted = json.loads(
            (tmp_path / f"{records[0].evidence_id}.json").read_text(encoding="utf-8")
        )
        assert persisted["schema_version"] == 2
        assert not any(
            event[0] in {"write_goal_positions", "stop_or_hold", "scan", "home"}
            for event in bus_factory.bus.events
        )
        assert service.status().state is FieldAcceptanceEvidenceState.VALID
        assert service.status().effective_status is FieldAcceptanceStatus.PENDING

    asyncio.run(scenario())


def test_pre_motion_publication_linearizes_before_concurrent_revoke() -> None:
    async def scenario() -> None:
        context = _unaccepted_context(read_only=True)
        clock = FakeClock()
        device, _, _ = device_service(context, clock=clock)
        repository = BarrierFieldAcceptanceRepository(asyncio.get_running_loop())
        service = FieldAcceptanceService(
            device=device,
            repository=repository,
            clock=clock,
        )
        issued = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
            operator_id="linearized-pre-motion-operator",
        )
        token = issued.session_token.get_secret_value()
        await device.connect(token)

        accepting = asyncio.create_task(
            service.complete_pre_motion_checks(
                token,
                checklist_version=context.field_acceptance_checklist_version,
            )
        )
        await asyncio.wait_for(repository.saved.wait(), timeout=1.0)
        revoking = asyncio.create_task(device.revoke_operator_session(token))
        await asyncio.sleep(0)
        assert revoking.done() is False

        repository.release.set()
        progress = await asyncio.wait_for(accepting, timeout=1.0)
        await asyncio.wait_for(revoking, timeout=1.0)

        assert progress.pre_motion_checks_complete is True
        assert len(repository.values) == 1
        assert device.context.field_acceptance_evidence is not None
        assert (
            FieldAcceptanceCapability.PRE_MOTION_CHECKS
            in device.context.field_acceptance_bundle.valid_capabilities(device.context)
        )
        assert (await device.sessions.status()).active is False

    asyncio.run(scenario())


def test_concurrent_revoke_wins_before_pre_motion_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        context = _unaccepted_context(read_only=True)
        clock = FakeClock()
        device, _, _ = device_service(context, clock=clock)
        repository = BarrierFieldAcceptanceRepository(asyncio.get_running_loop())
        service = FieldAcceptanceService(
            device=device,
            repository=repository,
            clock=clock,
        )
        issued = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
            operator_id="revoked-pre-motion-operator",
        )
        token = issued.session_token.get_secret_value()
        await device.connect(token)

        apply_reached = asyncio.Event()
        release_apply = asyncio.Event()
        original_apply = device.apply_field_acceptance_evidence

        async def delayed_apply(
            evidence: FieldAcceptanceEvidence,
            *,
            validated_bundle: ValidatedFieldAcceptanceBundle,
            token: str,
            expected_session_id: UUID,
            persist: Callable[[], Awaitable[None]],
        ) -> None:
            apply_reached.set()
            await release_apply.wait()
            await original_apply(
                evidence,
                validated_bundle=validated_bundle,
                token=token,
                expected_session_id=expected_session_id,
                persist=persist,
            )

        monkeypatch.setattr(device, "apply_field_acceptance_evidence", delayed_apply)
        accepting = asyncio.create_task(
            service.complete_pre_motion_checks(
                token,
                checklist_version=context.field_acceptance_checklist_version,
            )
        )
        await asyncio.wait_for(apply_reached.wait(), timeout=1.0)
        await device.revoke_operator_session(token)
        release_apply.set()

        with pytest.raises(OperatorSessionTokenError):
            await asyncio.wait_for(accepting, timeout=1.0)
        assert repository.list_evidence() == ()
        assert device.context.field_acceptance_evidence is None
        assert (
            device.context.field_acceptance_bundle.valid_capabilities(device.context) == frozenset()
        )

    asyncio.run(scenario())


def test_pre_motion_requires_fresh_exact_diagnostics_and_disabled_torque(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        context = _unaccepted_context(read_only=True)
        assert context.device is not None
        clock = FakeClock()
        enabled_torque = {
            servo_id: servo_id == context.device.servo_ids[0]
            for servo_id in context.device.servo_ids
        }
        bus = fake_bus(context, torque_states=enabled_torque)
        device, _, _ = device_service(context, bus=bus, clock=clock)
        service = FieldAcceptanceService(
            device=device,
            repository=FileFieldAcceptanceEvidenceRepository(tmp_path, clock),
            clock=clock,
        )
        issued = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        token = issued.session_token.get_secret_value()
        await device.connect(token)

        with pytest.raises(FieldAcceptancePrerequisiteError) as failure:
            await service.complete_pre_motion_checks(
                token,
                checklist_version=context.field_acceptance_checklist_version,
            )
        assert "TORQUE_NOT_CONFIRMED_DISABLED" in str(failure.value.details)
        assert service.repository.list_evidence() == ()

    asyncio.run(scenario())


def test_joint_acceptance_requires_every_current_joint_both_directions_and_stop_path(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        context = _pre_motion_context()
        assert context.profile is not None
        clock = FakeClock()
        device, _, _ = device_service(context, clock=clock)
        field_repository = FileFieldAcceptanceEvidenceRepository(tmp_path / "field", clock)
        pre_motion = context.field_acceptance_bundle.newest_for(
            FieldAcceptanceCapability.PRE_MOTION_CHECKS
        )
        assert pre_motion is not None
        field_repository.save(pre_motion)
        test_repository = FileCommissioningTestEvidenceRepository(tmp_path / "tests", clock)
        service = FieldAcceptanceService(
            device=device,
            repository=field_repository,
            commissioning_repository=test_repository,
            clock=clock,
        )

        evidence_by_key: dict[tuple[str, CommissioningDirection], CommissioningTestEvidence] = {}
        for joint_id in context.profile.enabled_joints:
            for direction in CommissioningDirection:
                evidence = _joint_test_evidence(context, joint_id, direction, clock)
                evidence_by_key[(joint_id, direction)] = evidence
                await test_repository.save(evidence)

        # A stale robot-unit record and an unverified software Stop record remain
        # audit data and are never selected even though their result says PASSED.
        stale = _joint_test_evidence(
            context,
            context.profile.enabled_joints[0],
            CommissioningDirection.POSITIVE,
            clock,
            robot_unit_id="MOMO-V2-UNIT-STALE",
        )
        no_stop = _joint_test_evidence(
            context,
            context.profile.enabled_joints[0],
            CommissioningDirection.NEGATIVE,
            clock,
            stop_behavior=StopBehavior.NOT_REQUESTED,
        )
        await test_repository.save(stale)
        await test_repository.save(no_stop)

        missing = evidence_by_key[
            (
                context.profile.enabled_joints[-1],
                CommissioningDirection.NEGATIVE,
            )
        ]
        # Recreate a repository missing exactly one required direction.
        incomplete_repository = FileCommissioningTestEvidenceRepository(
            tmp_path / "incomplete-tests",
            clock,
        )
        for evidence in evidence_by_key.values():
            if evidence.id != missing.id:
                await incomplete_repository.save(evidence)
        incomplete_service = FieldAcceptanceService(
            device=device,
            repository=field_repository,
            commissioning_repository=incomplete_repository,
            clock=clock,
        )
        issued = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.COMMISSIONING_MOTION_TEST,
            confirmation_text=REQUIRED_COMMISSIONING_MOTION_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
            workspace_clear_confirmed=True,
            operator_id="joint-acceptance-operator",
        )
        token = issued.session_token.get_secret_value()
        with pytest.raises(JointTestEvidenceIncompleteError) as incomplete:
            await incomplete_service.accept_joint_motion(
                token,
                checklist_version=context.field_acceptance_checklist_version,
            )
        assert isinstance(incomplete.value.details, dict)
        assert incomplete.value.details["completed_joint_directions"] == (
            len(context.profile.enabled_joints) * 2 - 1
        )
        assert not any(
            item.capability is FieldAcceptanceCapability.JOINT_MOTION
            for item in field_repository.list_evidence()
        )

        progress_before = await service.progress()
        assert progress_before.joint_motion_tests_complete is True
        assert progress_before.ready_to_accept_joint_motion is True
        assert set(progress_before.rejected_test_evidence_ids) == {stale.id, no_stop.id}

        progress = await service.accept_joint_motion(
            token,
            checklist_version=context.field_acceptance_checklist_version,
        )

        assert progress.joint_motion_accepted is True
        assert progress.state is FieldAcceptanceProgressState.KINEMATICS_VERIFICATION_PENDING
        assert progress.physical_stop_verification is PhysicalStopVerification.PENDING
        assert progress.full_acceptance_complete is False
        assert len(progress.selected_test_evidence_ids) == len(context.profile.enabled_joints) * 2
        assert all(item.complete for item in progress.joints)
        joint_acceptance = max(
            (
                item
                for item in field_repository.list_evidence()
                if item.capability is FieldAcceptanceCapability.JOINT_MOTION
            ),
            key=lambda item: item.accepted_at,
        )
        assert joint_acceptance.accepted_by == "joint-acceptance-operator"
        assert set(joint_acceptance.test_evidence_ids) == set(progress.selected_test_evidence_ids)
        assert (await device.sessions.status()).active is False
        with pytest.raises(OperatorSessionTokenError):
            await device.authorize_operator_purpose(
                token,
                purpose=(RealHardwareAuthorizationPurpose.COMMISSIONING_SINGLE_JOINT_TEST),
            )

    asyncio.run(scenario())


def test_legacy_v1_records_reload_as_stale_audit_only(tmp_path: Path) -> None:
    async def scenario() -> None:
        context = _unaccepted_context()
        assert context.profile is not None
        assert context.calibration is not None
        assert context.device is not None
        clock = FakeClock()
        legacy = FieldAcceptanceEvidence.model_validate(
            {
                "schema_version": 1,
                "revision": 1,
                "status": "PASSED",
                "robot_variant": context.profile.variant,
                "profile_fingerprint": context.profile.fingerprint,
                "calibration_fingerprint": calibration_fingerprint(context.calibration),
                "device_fingerprint": explicit_device_fingerprint(context.device),
                "checklist_version": context.field_acceptance_checklist_version,
                "accepted_at": clock.now(),
                "accepted_by": "legacy-audit-operator",
            }
        )
        repository = FileFieldAcceptanceEvidenceRepository(tmp_path, clock)
        repository.save(legacy)
        reloaded = FileFieldAcceptanceEvidenceRepository(tmp_path, clock)
        assert reloaded.list_evidence() == (legacy,)
        device, _, _ = device_service(context, clock=clock)
        service = FieldAcceptanceService(
            device=device,
            repository=reloaded,
            clock=clock,
        )

        progress = await service.progress()

        assert progress.legacy_field_acceptance_evidence_ids == (legacy.evidence_id,)
        assert progress.valid_capabilities == ()
        assert progress.full_acceptance_complete is False
        assert service.status().state is FieldAcceptanceEvidenceState.STALE_LEGACY_EVIDENCE
        assert service.status().effective_status is FieldAcceptanceStatus.PENDING

    asyncio.run(scenario())


def test_restart_resolver_keeps_typed_pre_motion_but_rejects_bare_joint_uuid() -> None:
    context = _unaccepted_context()
    clock = FakeClock()
    pre_motion = FieldAcceptanceEvidence.for_capability(
        context=context,
        capability=FieldAcceptanceCapability.PRE_MOTION_CHECKS,
        checklist_version=context.field_acceptance_checklist_version,
        test_evidence_ids=(),
        accepted_at=clock.now(),
        accepted_by="synthetic-read-only-operator",
        software_commit=context.software_commit,
        pre_motion_snapshot=synthetic_pre_motion_snapshot(context, clock.now()),
    )
    forged_joint = FieldAcceptanceEvidence.for_capability(
        context=context,
        capability=FieldAcceptanceCapability.JOINT_MOTION,
        checklist_version=context.field_acceptance_checklist_version,
        test_evidence_ids=(uuid4(),),
        accepted_at=clock.now(),
        accepted_by="cannot-forge-evidence-chain",
        software_commit=context.software_commit,
    )

    audit_only = FieldAcceptanceBundle(records=(pre_motion, forged_joint))
    assert audit_only.valid_capabilities(context) == frozenset()
    resolved = validated_field_acceptance_bundle(
        context,
        audit_only.records,
        (),
    )
    assert resolved.valid_capabilities(context) == frozenset(
        {FieldAcceptanceCapability.PRE_MOTION_CHECKS}
    )


def test_joint_resolver_requires_every_link_and_the_exact_effective_envelope() -> None:
    context = _pre_motion_context()
    assert context.profile is not None
    clock = FakeClock()
    pre_motion = context.field_acceptance_bundle.newest_for(
        FieldAcceptanceCapability.PRE_MOTION_CHECKS
    )
    assert pre_motion is not None
    records = tuple(
        _joint_test_evidence(context, joint_id, direction, clock)
        for joint_id in context.profile.enabled_joints
        for direction in CommissioningDirection
    )
    acceptance = FieldAcceptanceEvidence.for_capability(
        context=context,
        capability=FieldAcceptanceCapability.JOINT_MOTION,
        checklist_version=context.field_acceptance_checklist_version,
        test_evidence_ids=tuple(item.id for item in records),
        accepted_at=clock.now(),
        accepted_by="synthetic-chain-reviewer",
        software_commit=context.software_commit,
    )
    resolved = validated_field_acceptance_bundle(
        context,
        (pre_motion, acceptance),
        records,
    )
    assert FieldAcceptanceCapability.JOINT_MOTION in resolved.valid_capabilities(context)

    prepared = records[0].prepared_command
    assert prepared is not None
    mismatched = records[0].model_copy(
        update={
            "prepared_command": prepared.model_copy(
                update={"envelope": CommissioningSafetyEnvelope(max_revolute_delta_deg=1.0)}
            )
        }
    )
    rejected = validated_field_acceptance_bundle(
        context,
        (pre_motion, acceptance),
        (mismatched, *records[1:]),
    )
    assert FieldAcceptanceCapability.JOINT_MOTION not in rejected.valid_capabilities(context)
