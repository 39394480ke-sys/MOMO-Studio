"""Stage 8 Real executor tests with a deterministic in-memory ServoBus only."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import timedelta
from typing import NoReturn, cast
from uuid import UUID, uuid4

import pytest

from momo.adapters.motion.real_motion_executor import RealMotionExecutor
from momo.domain.calibration import CalibrationDocument
from momo.domain.enums import ControlMode, Easing, HardwareAccessPolicy
from momo.domain.real_hardware import (
    RealHardwareAuthorizationPurpose,
    RealHardwareCapabilityReadiness,
    RealStopOutcome,
    RealStopResult,
    ServoPingResult,
    ServoWriteResult,
    calibration_fingerprint,
)
from momo.domain.real_motion import (
    RealExecutionAuthorization,
    RealExecutionContext,
    RealMotionAuditEvent,
    RealMotionAuditKind,
    RealMotionError,
    RealMotionFaultCode,
    RealMotionState,
    RealMotionStatus,
)
from momo.domain.robot import JointState, RobotProfile
from momo.domain.trajectory import (
    PreparedTrajectory,
    TrajectoryDigest,
    TrajectoryPlan,
    TrajectoryPreflightCheck,
    TrajectoryPreflightReport,
    TrajectorySample,
    TrajectorySegment,
    TrajectorySegmentKind,
)
from tests.stage3_helpers import FakeClock
from tests.stage8_hardware_helpers import real_calibration, real_profile


class MutableExecutionContextProvider:
    def __init__(
        self,
        clock: FakeClock,
        profile: RobotProfile,
        calibration: CalibrationDocument,
        kinematics_fingerprint: str,
    ) -> None:
        self.clock = clock
        self.profile = profile
        self.calibration = calibration
        self.kinematics_fingerprint = kinematics_fingerprint
        self.context: RealExecutionContext | None = None
        self.calls = 0

    def bind(self, prepared: PreparedTrajectory, **updates: object) -> None:
        first = prepared.plan.samples[0]
        values: dict[str, object] = {
            "robot_id": "primary",
            "variant": self.profile.variant,
            "connected": True,
            "state_fresh": True,
            "stop_capable": True,
            "state_sequence": prepared.plan.start_state_sequence,
            "joint_state": JointState(
                positions=dict(first.positions),
                units=dict(first.units),
            ),
            "motion_id": prepared.plan.motion_id,
            "motion_revision": prepared.plan.motion_revision,
            "trajectory_digest": prepared.plan.digest.sha256,
            "profile_fingerprint": self.profile.fingerprint,
            "calibration_fingerprint": calibration_fingerprint(self.calibration),
            "kinematics_fingerprint": self.kinematics_fingerprint,
            "observed_at": self.clock.now(),
        }
        values.update(updates)
        self.context = RealExecutionContext.model_validate(values)

    async def current_real_execution_context(self) -> RealExecutionContext:
        self.calls += 1
        if self.context is None:
            raise RuntimeError("synthetic context is not bound")
        return self.context

    def apply_readback(self, state: JointState) -> int:
        assert self.context is not None
        next_sequence = self.context.state_sequence + 1
        self.context = self.context.model_copy(
            update={
                "state_sequence": next_sequence,
                "joint_state": state,
                "observed_at": self.clock.now(),
            }
        )
        return next_sequence

    def mutate(self, **updates: object) -> None:
        assert self.context is not None
        self.context = self.context.model_copy(update=updates)


class RecordingObserver:
    def __init__(self, context_provider: MutableExecutionContextProvider) -> None:
        self.context_provider = context_provider
        self.states: list[tuple[UUID, JointState]] = []
        self.audit: list[RealMotionAuditEvent] = []

    async def apply_real_readback(self, execution_id: UUID, state: JointState) -> int:
        self.states.append((execution_id, state))
        return self.context_provider.apply_readback(state)

    async def record_real_motion_audit(self, event: RealMotionAuditEvent) -> None:
        self.audit.append(event)


class MotionFakeBus:
    """Configurable exact-ID fake; it never imports or wraps a hardware SDK."""

    def __init__(
        self,
        positions: Mapping[int, int],
        clock: FakeClock,
        *,
        behavior: str = "normal",
        stop_result: RealStopResult = RealStopResult.STOPPED_AND_VERIFIED,
        write_work_s: float = 0.0,
    ) -> None:
        self.positions = dict(positions)
        self.clock = clock
        self.behavior = behavior
        self.stop_result = stop_result
        self.write_work_s = write_work_s
        self.events: list[tuple[str, object]] = []
        self.write_times: list[float] = []

    async def write_goal_positions(
        self,
        goal_positions: Mapping[int, int],
    ) -> ServoWriteResult:
        goals = dict(goal_positions)
        requested = tuple(goals)
        self.events.append(("write_goal_positions", goals))
        self.write_times.append(self.clock.monotonic())
        if self.write_work_s:
            self.clock.elapse(self.write_work_s)
        if self.behavior == "hang_write":
            await asyncio.Event().wait()
        if self.behavior == "fault":
            raise RuntimeError("synthetic bus write fault")
        if self.behavior == "disconnected":
            return ServoWriteResult(
                requested_ids=requested,
                written_ids=(),
                failed_ids=requested,
                connected=False,
                complete=False,
                safety_state_known=False,
                detail="synthetic disconnected write",
            )
        if self.behavior == "unknown":
            return ServoWriteResult(
                requested_ids=requested,
                written_ids=(),
                failed_ids=requested,
                connected=True,
                complete=False,
                safety_state_known=False,
                detail="synthetic unknown safety state",
            )
        if self.behavior == "partial":
            written = requested[:-1]
            failed = requested[-1:]
            for servo_id in written:
                self.positions[servo_id] = goals[servo_id]
            return ServoWriteResult(
                requested_ids=requested,
                written_ids=written,
                failed_ids=failed,
                connected=True,
                complete=False,
                safety_state_known=True,
                detail="synthetic partial write",
            )
        self.positions.update(goals)
        if self.behavior == "divergence":
            self.positions[requested[0]] += 50
        return ServoWriteResult(
            requested_ids=requested,
            written_ids=requested,
            failed_ids=(),
            connected=True,
            complete=True,
            safety_state_known=True,
            detail="synthetic complete write",
        )

    async def read_present_positions(self, servo_ids: tuple[int, ...]) -> Mapping[int, int]:
        self.events.append(("read_present_positions", servo_ids))
        if self.behavior == "hang_read":
            await asyncio.Event().wait()
        if self.behavior == "read_fault":
            raise RuntimeError("synthetic readback fault")
        return {servo_id: self.positions[servo_id] for servo_id in servo_ids}

    async def stop_or_hold(self, servo_ids: tuple[int, ...]) -> RealStopOutcome:
        self.events.append(("stop_or_hold", servo_ids))
        if self.behavior == "hang_stop":
            await asyncio.Event().wait()
        if self.stop_result is RealStopResult.STOPPED_AND_VERIFIED:
            return RealStopOutcome(
                result=self.stop_result,
                requested_ids=servo_ids,
                affected_ids=servo_ids,
                connected=True,
                safety_state_known=True,
                detail="synthetic Stop verified",
            )
        if self.stop_result is RealStopResult.NOT_CONNECTED:
            return RealStopOutcome(
                result=self.stop_result,
                requested_ids=servo_ids,
                affected_ids=(),
                connected=False,
                safety_state_known=False,
                detail="synthetic Stop not connected",
            )
        affected = (
            servo_ids
            if self.stop_result
            in {RealStopResult.HOLD_REQUESTED, RealStopResult.TORQUE_DISABLE_REQUESTED}
            else ()
        )
        return RealStopOutcome(
            result=self.stop_result,
            requested_ids=servo_ids,
            affected_ids=affected,
            connected=True,
            safety_state_known=False,
            detail="synthetic Stop intentionally unverified",
        )

    async def open(self, device: str, protocol: str) -> NoReturn:
        del device, protocol
        self._forbidden("open")

    async def close(self) -> NoReturn:
        self._forbidden("close")

    async def ping_explicit_ids(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, ServoPingResult]:
        del servo_ids
        self._forbidden("ping_explicit_ids")

    async def read_operating_modes(self, servo_ids: tuple[int, ...]) -> Mapping[int, str]:
        del servo_ids
        self._forbidden("read_operating_modes")

    async def read_torque_states(self, servo_ids: tuple[int, ...]) -> Mapping[int, bool]:
        del servo_ids
        self._forbidden("read_torque_states")

    def _forbidden(self, name: str) -> NoReturn:
        self.events.append((name, None))
        raise AssertionError(f"RealMotionExecutor must never call {name}")


def explicit_servo_ids(profile: RobotProfile) -> tuple[int, ...]:
    return tuple(cast(int, definition.servo_id) for definition in profile.joint_definitions)


def execution_authorization(
    profile: RobotProfile,
    calibration: CalibrationDocument,
    clock: FakeClock,
    *,
    expires_in_s: float = 60.0,
    purpose: RealHardwareAuthorizationPurpose = (
        RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION
    ),
) -> RealExecutionAuthorization:
    capabilities = RealHardwareCapabilityReadiness(
        real_joint_motion_ready=True,
        real_cartesian_motion_ready=(
            purpose is RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION
        ),
        real_playback_ready=(purpose is RealHardwareAuthorizationPurpose.REAL_PLAYBACK),
    )
    return RealExecutionAuthorization(
        session_id=uuid4(),
        robot_id="primary",
        variant=profile.variant,
        profile_fingerprint=profile.fingerprint,
        calibration_fingerprint=calibration_fingerprint(calibration),
        allowed_servo_ids=explicit_servo_ids(profile),
        issued_at=clock.now(),
        expires_at=clock.now() + timedelta(seconds=expires_in_s),
        confirmed=True,
        control_mode=ControlMode.REAL,
        hardware_policy=HardwareAccessPolicy.FULL,
        purpose=purpose,
        capabilities=capabilities,
    )


def prepared_trajectory(
    profile: RobotProfile,
    clock: FakeClock,
    kinematics_fingerprint: str,
    *,
    times: tuple[float, ...] = (0.0, 1.0),
    first_joint_values: tuple[float, ...] = (0.0, 1.0),
    segment_kind: TrajectorySegmentKind = TrajectorySegmentKind.JOINT,
) -> PreparedTrajectory:
    assert len(times) == len(first_joint_values) and len(times) >= 2
    motion_id = uuid4()
    start_keyframe_id = uuid4()
    end_keyframe_id = uuid4()
    duration_s = times[-1]
    samples = [
        TrajectorySample(
            time_s=time_s,
            positions={
                joint_id: (
                    first_joint_values[index] if joint_id == profile.enabled_joints[0] else 0.0
                )
                for joint_id in profile.enabled_joints
            },
            units={
                joint_id: profile.definitions_by_id[joint_id].domain_unit
                for joint_id in profile.enabled_joints
            },
            keyframe_id=start_keyframe_id if index == 0 else end_keyframe_id,
            segment_index=0,
            sample_index=index,
        )
        for index, time_s in enumerate(times)
    ]
    segment = TrajectorySegment(
        segment_index=0,
        kind=segment_kind,
        from_keyframe_id=start_keyframe_id,
        to_keyframe_id=end_keyframe_id,
        easing=Easing.LINEAR,
        start_time_s=0.0,
        end_time_s=duration_s,
        duration_s=duration_s,
        start_sample_index=0,
        end_sample_index=len(samples) - 1,
        generated_sample_count=len(samples) - 1,
    )
    sample_rate_hz = (len(samples) - 1) / duration_s
    draft = TrajectoryPlan.model_construct(
        schema_version="1.0.0",
        motion_id=motion_id,
        motion_revision=1,
        robot_variant=profile.variant,
        profile_fingerprint=profile.fingerprint,
        kinematics_fingerprint=kinematics_fingerprint,
        start_state_sequence=7,
        sample_rate_hz=sample_rate_hz,
        duration_s=duration_s,
        segments=[segment],
        samples=samples,
        digest=TrajectoryDigest(sha256="0" * 64),
        compiled_at=clock.now(),
    )
    digest = TrajectoryDigest(sha256=draft.computed_sha256)
    plan = TrajectoryPlan(
        motion_id=motion_id,
        motion_revision=1,
        robot_variant=profile.variant,
        profile_fingerprint=profile.fingerprint,
        kinematics_fingerprint=kinematics_fingerprint,
        start_state_sequence=7,
        sample_rate_hz=sample_rate_hz,
        duration_s=duration_s,
        segments=[segment],
        samples=samples,
        digest=digest,
        compiled_at=clock.now(),
    )
    report = TrajectoryPreflightReport(
        accepted=True,
        motion_id=motion_id,
        motion_revision=1,
        digest=digest,
        duration_s=duration_s,
        sample_count=len(samples),
        segment_count=1,
        sample_rate_hz=sample_rate_hz,
        checks=[
            TrajectoryPreflightCheck(
                name="synthetic-stage8",
                passed=True,
                detail="Synthetic accepted plan for Fake ServoBus execution",
            )
        ],
        violations=[],
    )
    return PreparedTrajectory(plan=plan, preflight=report)


def executor_fixture(
    *,
    behavior: str = "normal",
    stop_result: RealStopResult = RealStopResult.STOPPED_AND_VERIFIED,
    write_work_s: float = 0.0,
    bus_operation_timeout_s: float = 1.0,
) -> tuple[
    RealMotionExecutor,
    MotionFakeBus,
    RecordingObserver,
    MutableExecutionContextProvider,
    FakeClock,
    RobotProfile,
    CalibrationDocument,
    str,
]:
    clock = FakeClock()
    profile = real_profile()
    calibration = real_calibration(profile)
    kinematics_fingerprint = "c" * 64
    bus = MotionFakeBus(
        {servo_id: 0 for servo_id in explicit_servo_ids(profile)},
        clock,
        behavior=behavior,
        stop_result=stop_result,
        write_work_s=write_work_s,
    )
    context_provider = MutableExecutionContextProvider(
        clock,
        profile,
        calibration,
        kinematics_fingerprint,
    )
    observer = RecordingObserver(context_provider)
    executor = RealMotionExecutor(
        bus,
        clock,
        robot_id="primary",
        profile=profile,
        calibration=calibration,
        kinematics_fingerprint=kinematics_fingerprint,
        context_provider=context_provider,
        observer=observer,
        divergence_tolerance_raw=8,
        bus_operation_timeout_s=bus_operation_timeout_s,
    )
    return (
        executor,
        bus,
        observer,
        context_provider,
        clock,
        profile,
        calibration,
        kinematics_fingerprint,
    )


def test_exact_prepared_trajectory_runs_on_monotonic_deadlines_with_readback() -> None:
    async def scenario() -> tuple[RealMotionStatus, MotionFakeBus, RecordingObserver]:
        (
            executor,
            bus,
            observer,
            context_provider,
            clock,
            profile,
            calibration,
            kinematics,
        ) = executor_fixture()
        prepared = prepared_trajectory(profile, clock, kinematics)
        context_provider.bind(prepared)
        accepted = await executor.submit(
            prepared,
            expected_digest=prepared.plan.digest.sha256,
            authorization=execution_authorization(profile, calibration, clock),
            execution_purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
        )
        assert accepted.state is RealMotionState.ACCEPTED
        await clock.settle()
        assert len(bus.write_times) == 1
        await clock.advance(1.0)
        terminal = await executor.wait(accepted.execution_id)
        return terminal, bus, observer

    terminal, bus, observer = asyncio.run(scenario())

    assert terminal.state is RealMotionState.COMPLETED
    assert terminal.progress == 1.0
    assert terminal.hardware_accessed is True
    assert terminal.safety_state_known is True
    assert terminal.physical_estop_claimed is False
    assert bus.write_times == [0.0, 1.0]
    expected_ids = explicit_servo_ids(real_profile())
    for name, payload in bus.events:
        if name == "write_goal_positions":
            assert tuple(cast(dict[int, int], payload)) == expected_ids
        elif name == "read_present_positions":
            assert payload == expected_ids
    assert [name for name, _ in bus.events] == [
        "write_goal_positions",
        "read_present_positions",
        "write_goal_positions",
        "read_present_positions",
    ]
    assert len(observer.states) == 2
    assert [event.kind for event in observer.audit] == [
        RealMotionAuditKind.ACCEPTED,
        RealMotionAuditKind.WRITE,
        RealMotionAuditKind.READBACK,
        RealMotionAuditKind.WRITE,
        RealMotionAuditKind.READBACK,
        RealMotionAuditKind.TERMINAL,
    ]
    assert all(event.physical_estop_claimed is False for event in observer.audit)


@pytest.mark.parametrize(
    ("behavior", "expected_code"),
    [
        ("partial", RealMotionFaultCode.PARTIAL_WRITE),
        ("disconnected", RealMotionFaultCode.BUS_DISCONNECTED),
        ("unknown", RealMotionFaultCode.SAFETY_STATE_UNCERTAIN),
        ("fault", RealMotionFaultCode.BUS_FAULT),
        ("read_fault", RealMotionFaultCode.BUS_FAULT),
        ("divergence", RealMotionFaultCode.READBACK_DIVERGENCE),
    ],
)
def test_write_readback_and_connection_failures_stop_and_fault_truthfully(
    behavior: str,
    expected_code: RealMotionFaultCode,
) -> None:
    async def scenario() -> tuple[RealMotionStatus, MotionFakeBus]:
        executor, bus, _, context_provider, clock, profile, calibration, kinematics = (
            executor_fixture(behavior=behavior)
        )
        prepared = prepared_trajectory(profile, clock, kinematics)
        context_provider.bind(prepared)
        accepted = await executor.submit(
            prepared,
            expected_digest=prepared.plan.digest.sha256,
            authorization=execution_authorization(profile, calibration, clock),
            execution_purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
        )
        await clock.settle()
        return await executor.wait(accepted.execution_id), bus

    terminal, bus = asyncio.run(scenario())

    assert terminal.state is RealMotionState.FAULTED
    assert terminal.fault_code is expected_code
    assert terminal.stop_outcome is not None
    assert terminal.stop_outcome.result is RealStopResult.STOPPED_AND_VERIFIED
    assert terminal.physical_estop_claimed is False
    assert [name for name, _ in bus.events].count("stop_or_hold") == 1
    stop_payload = next(payload for name, payload in bus.events if name == "stop_or_hold")
    assert stop_payload == explicit_servo_ids(real_profile())


def test_cancellation_requires_verified_stop_and_unverified_hold_is_not_cancelled() -> None:
    async def run_case(stop_result: RealStopResult) -> RealMotionStatus:
        executor, _, _, context_provider, clock, profile, calibration, kinematics = (
            executor_fixture(stop_result=stop_result)
        )
        prepared = prepared_trajectory(profile, clock, kinematics)
        context_provider.bind(prepared)
        accepted = await executor.submit(
            prepared,
            expected_digest=prepared.plan.digest.sha256,
            authorization=execution_authorization(profile, calibration, clock),
            execution_purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
        )
        await clock.settle()
        terminal = await executor.cancel_active()
        assert terminal is not None and terminal.execution_id == accepted.execution_id
        return terminal

    verified = asyncio.run(run_case(RealStopResult.STOPPED_AND_VERIFIED))
    unverified = asyncio.run(run_case(RealStopResult.HOLD_REQUESTED))

    assert verified.state is RealMotionState.CANCELLED
    assert verified.safety_state_known is True
    assert unverified.state is RealMotionState.FAULTED
    assert unverified.fault_code is RealMotionFaultCode.SAFETY_STATE_UNCERTAIN
    assert unverified.safety_state_known is False
    assert unverified.stop_outcome is not None
    assert unverified.stop_outcome.result is RealStopResult.HOLD_REQUESTED


def test_session_expiry_auto_stops_before_the_next_sample() -> None:
    async def scenario() -> tuple[RealMotionStatus, MotionFakeBus]:
        executor, bus, _, context_provider, clock, profile, calibration, kinematics = (
            executor_fixture()
        )
        prepared = prepared_trajectory(profile, clock, kinematics)
        context_provider.bind(prepared)
        accepted = await executor.submit(
            prepared,
            expected_digest=prepared.plan.digest.sha256,
            authorization=execution_authorization(
                profile,
                calibration,
                clock,
                expires_in_s=0.5,
            ),
            execution_purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
        )
        await clock.settle()
        await clock.advance(0.5)
        return await executor.wait(accepted.execution_id), bus

    terminal, bus = asyncio.run(scenario())

    assert terminal.state is RealMotionState.FAULTED
    assert terminal.fault_code is RealMotionFaultCode.AUTHORIZATION_EXPIRED
    assert [name for name, _ in bus.events].count("write_goal_positions") == 1
    assert [name for name, _ in bus.events].count("stop_or_hold") == 1


def test_overdue_samples_are_skipped_instead_of_replayed_as_a_write_burst() -> None:
    async def scenario() -> tuple[RealMotionStatus, MotionFakeBus, RecordingObserver]:
        (
            executor,
            bus,
            observer,
            context_provider,
            clock,
            profile,
            calibration,
            kinematics,
        ) = executor_fixture(write_work_s=0.76)
        prepared = prepared_trajectory(
            profile,
            clock,
            kinematics,
            times=(0.0, 0.25, 0.5, 0.75, 1.0),
            first_joint_values=(0.0, 0.1, 0.2, 0.3, 0.4),
        )
        context_provider.bind(prepared)
        accepted = await executor.submit(
            prepared,
            expected_digest=prepared.plan.digest.sha256,
            authorization=execution_authorization(profile, calibration, clock),
            execution_purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
        )
        await clock.settle()
        return await executor.wait(accepted.execution_id), bus, observer

    terminal, bus, observer = asyncio.run(scenario())

    assert terminal.state is RealMotionState.COMPLETED
    assert len(bus.write_times) == 3
    written_sample_indices = [
        event.sample_index for event in observer.audit if event.kind is RealMotionAuditKind.WRITE
    ]
    assert written_sample_indices == [
        0,
        3,
        4,
    ]


def test_capability_digest_and_raw_mapping_rejections_precede_hardware_access() -> None:
    async def scenario() -> tuple[list[str], MotionFakeBus]:
        executor, bus, _, context_provider, clock, profile, calibration, kinematics = (
            executor_fixture()
        )
        authorization = execution_authorization(profile, calibration, clock)
        valid = prepared_trajectory(profile, clock, kinematics)
        context_provider.bind(valid)
        codes: list[str] = []
        diagnostics_only = authorization.model_copy(
            update={"purpose": RealHardwareAuthorizationPurpose.DIAGNOSTICS}
        )
        with pytest.raises(RealMotionError) as capability_error:
            await executor.submit(
                valid,
                expected_digest=valid.plan.digest.sha256,
                authorization=diagnostics_only,
                execution_purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            )
        codes.append(capability_error.value.code)
        with pytest.raises(RealMotionError) as digest_error:
            await executor.submit(
                valid,
                expected_digest="f" * 64,
                authorization=authorization,
                execution_purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            )
        codes.append(digest_error.value.code)
        unmappable = prepared_trajectory(
            profile,
            clock,
            kinematics,
            first_joint_values=(0.0, 999.0),
        )
        context_provider.bind(unmappable)
        with pytest.raises(RealMotionError) as raw_error:
            await executor.submit(
                unmappable,
                expected_digest=unmappable.plan.digest.sha256,
                authorization=authorization,
                execution_purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            )
        codes.append(raw_error.value.code)
        return codes, bus

    codes, bus = asyncio.run(scenario())

    assert codes == [
        RealMotionFaultCode.AUTHORIZATION_MISMATCH.value,
        RealMotionFaultCode.PREPARED_TRAJECTORY_CHANGED.value,
        RealMotionFaultCode.RAW_MAPPING_INVALID.value,
    ]
    assert bus.events == []


def test_profile_logical_limits_are_checked_before_raw_mapping_or_bus_access() -> None:
    async def scenario() -> tuple[str, MotionFakeBus]:
        executor, bus, _, context_provider, clock, profile, calibration, kinematics = (
            executor_fixture()
        )
        outside_logical_limit = prepared_trajectory(
            profile,
            clock,
            kinematics,
            first_joint_values=(0.0, 1001.0),
        )
        context_provider.bind(outside_logical_limit)
        with pytest.raises(RealMotionError) as error:
            await executor.submit(
                outside_logical_limit,
                expected_digest=outside_logical_limit.plan.digest.sha256,
                authorization=execution_authorization(profile, calibration, clock),
                execution_purpose=(RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION),
            )
        return error.value.code, bus

    code, bus = asyncio.run(scenario())

    assert code == RealMotionFaultCode.RAW_MAPPING_INVALID.value
    assert bus.events == []


@pytest.mark.parametrize(
    ("purpose", "segment_kind"),
    [
        (
            RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION,
            TrajectorySegmentKind.CARTESIAN_LINEAR,
        ),
        (
            RealHardwareAuthorizationPurpose.REAL_PLAYBACK,
            TrajectorySegmentKind.JOINT,
        ),
    ],
)
def test_explicit_execution_purpose_and_matching_segment_capability_are_required(
    purpose: RealHardwareAuthorizationPurpose,
    segment_kind: TrajectorySegmentKind,
) -> None:
    async def scenario() -> tuple[RealMotionStatus, list[str]]:
        executor, _, _, context_provider, clock, profile, calibration, kinematics = (
            executor_fixture()
        )
        incompatible = prepared_trajectory(profile, clock, kinematics)
        authorization = execution_authorization(
            profile,
            calibration,
            clock,
            purpose=purpose,
        )
        codes: list[str] = []
        rejected_purpose = (
            RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION
            if purpose is RealHardwareAuthorizationPurpose.REAL_PLAYBACK
            else purpose
        )
        with pytest.raises(RealMotionError) as mismatch:
            await executor.submit(
                incompatible,
                expected_digest=incompatible.plan.digest.sha256,
                authorization=authorization,
                execution_purpose=rejected_purpose,
            )
        codes.append(mismatch.value.code)
        matching = prepared_trajectory(
            profile,
            clock,
            kinematics,
            segment_kind=segment_kind,
        )
        context_provider.bind(matching)
        accepted = await executor.submit(
            matching,
            expected_digest=matching.plan.digest.sha256,
            authorization=authorization,
            execution_purpose=purpose,
        )
        await clock.settle()
        await clock.advance(1.0)
        return await executor.wait(accepted.execution_id), codes

    terminal, codes = asyncio.run(scenario())

    assert codes == [RealMotionFaultCode.AUTHORIZATION_MISMATCH.value]
    assert terminal.state is RealMotionState.COMPLETED
    assert terminal.execution_purpose is purpose


@pytest.mark.parametrize(
    ("drift", "expected_code"),
    [
        ("disconnected", RealMotionFaultCode.ROBOT_DISCONNECTED),
        ("stale", RealMotionFaultCode.ROBOT_STATE_STALE),
        ("no_stop", RealMotionFaultCode.STOP_CAPABILITY_UNAVAILABLE),
        ("sequence", RealMotionFaultCode.STATE_SEQUENCE_CHANGED),
        ("revision", RealMotionFaultCode.MOTION_ARTIFACT_CHANGED),
        ("digest", RealMotionFaultCode.MOTION_ARTIFACT_CHANGED),
        ("continuity", RealMotionFaultCode.FIRST_SAMPLE_DISCONTINUITY),
    ],
)
def test_fresh_mutable_context_is_required_before_the_first_bus_write(
    drift: str,
    expected_code: RealMotionFaultCode,
) -> None:
    async def scenario() -> tuple[RealMotionStatus, MotionFakeBus]:
        executor, bus, _, context_provider, clock, profile, calibration, kinematics = (
            executor_fixture()
        )
        prepared = prepared_trajectory(profile, clock, kinematics)
        updates: dict[str, object] = {}
        if drift == "disconnected":
            updates["connected"] = False
        elif drift == "stale":
            updates["state_fresh"] = False
        elif drift == "no_stop":
            updates["stop_capable"] = False
        elif drift == "sequence":
            updates["state_sequence"] = prepared.plan.start_state_sequence + 1
        elif drift == "revision":
            updates["motion_revision"] = prepared.plan.motion_revision + 1
        elif drift == "digest":
            updates["trajectory_digest"] = "f" * 64
        elif drift == "continuity":
            first = prepared.plan.samples[0]
            positions = dict(first.positions)
            positions[profile.enabled_joints[0]] = 1.0
            updates["joint_state"] = JointState(
                positions=positions,
                units=dict(first.units),
            )
        context_provider.bind(prepared, **updates)
        accepted = await executor.submit(
            prepared,
            expected_digest=prepared.plan.digest.sha256,
            authorization=execution_authorization(profile, calibration, clock),
            execution_purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
        )
        await clock.settle()
        return await executor.wait(accepted.execution_id), bus

    terminal, bus = asyncio.run(scenario())

    assert terminal.state is RealMotionState.FAULTED
    assert terminal.fault_code is expected_code
    assert [name for name, _ in bus.events].count("write_goal_positions") == 0
    assert [name for name, _ in bus.events].count("stop_or_hold") == 1


def test_context_drift_after_readback_stops_before_the_next_write() -> None:
    async def scenario() -> tuple[RealMotionStatus, MotionFakeBus]:
        executor, bus, _, context_provider, clock, profile, calibration, kinematics = (
            executor_fixture()
        )
        prepared = prepared_trajectory(profile, clock, kinematics)
        context_provider.bind(prepared)
        accepted = await executor.submit(
            prepared,
            expected_digest=prepared.plan.digest.sha256,
            authorization=execution_authorization(profile, calibration, clock),
            execution_purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
        )
        await clock.settle()
        assert [name for name, _ in bus.events].count("write_goal_positions") == 1
        context_provider.mutate(connected=False)
        await clock.advance(1.0)
        return await executor.wait(accepted.execution_id), bus

    terminal, bus = asyncio.run(scenario())

    assert terminal.fault_code is RealMotionFaultCode.ROBOT_DISCONNECTED
    assert [name for name, _ in bus.events].count("write_goal_positions") == 1
    assert [name for name, _ in bus.events].count("stop_or_hold") == 1


@pytest.mark.parametrize("behavior", ["hang_write", "hang_read"])
def test_bus_write_and_read_deadlines_fail_with_uncertain_safety(behavior: str) -> None:
    async def scenario() -> tuple[RealMotionStatus, MotionFakeBus]:
        executor, bus, _, context_provider, clock, profile, calibration, kinematics = (
            executor_fixture(behavior=behavior, bus_operation_timeout_s=0.01)
        )
        prepared = prepared_trajectory(profile, clock, kinematics)
        context_provider.bind(prepared)
        accepted = await executor.submit(
            prepared,
            expected_digest=prepared.plan.digest.sha256,
            authorization=execution_authorization(profile, calibration, clock),
            execution_purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
        )
        await asyncio.sleep(0.03)
        return await executor.wait(accepted.execution_id), bus

    terminal, bus = asyncio.run(scenario())

    assert terminal.state is RealMotionState.FAULTED
    assert terminal.fault_code is RealMotionFaultCode.SAFETY_STATE_UNCERTAIN
    assert [name for name, _ in bus.events].count("stop_or_hold") == 1


def test_concurrent_cancel_and_stop_terminalize_once_even_when_stop_times_out() -> None:
    async def scenario() -> tuple[RealMotionStatus, MotionFakeBus, tuple[object, ...]]:
        executor, bus, _, context_provider, clock, profile, calibration, kinematics = (
            executor_fixture(behavior="hang_stop", bus_operation_timeout_s=0.01)
        )
        prepared = prepared_trajectory(profile, clock, kinematics)
        context_provider.bind(prepared)
        accepted = await executor.submit(
            prepared,
            expected_digest=prepared.plan.digest.sha256,
            authorization=execution_authorization(profile, calibration, clock),
            execution_purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
        )
        await clock.settle()
        results = await asyncio.gather(
            executor.cancel_active(),
            executor.cancel_active(),
            executor.stop(),
        )
        return await executor.wait(accepted.execution_id), bus, results

    terminal, bus, results = asyncio.run(scenario())

    assert terminal.state is RealMotionState.FAULTED
    assert terminal.fault_code is RealMotionFaultCode.SAFETY_STATE_UNCERTAIN
    assert terminal.stop_outcome is not None
    assert terminal.stop_outcome.result is RealStopResult.SAFETY_STATE_UNCERTAIN
    assert [name for name, _ in bus.events].count("stop_or_hold") == 1
    assert all(result is not None for result in results)
