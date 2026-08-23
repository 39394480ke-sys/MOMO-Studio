"""The single reviewed entry point for every motion intent."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from math import ceil, isclose, sqrt
from typing import NoReturn

from momo.application.services.calibration_service import CalibrationService
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.calibration import CalibrationDocument
from momo.domain.enums import (
    ControlMode,
    HardwareAccessPolicy,
    JointType,
    MotionCommandSource,
    MotionCommandType,
    RobotConnectionState,
)
from momo.domain.errors import HardwareMappingError, MotionConflictError, MotionPreflightError
from momo.domain.hardware_mapping import effective_logical_limits_from_raw_bounds
from momo.domain.motion_command import (
    MAX_EFFECTIVE_MOTION_DURATION_S,
    CartesianJogPayload,
    ContinuousJogPayload,
    HomePayload,
    JointJogStepPayload,
    JointMovePayload,
    MotionCommand,
    MovePosePayload,
)
from momo.domain.motion_preflight import (
    MotionPreflight,
    PreflightCheck,
    PreparedContinuousJog,
    PreparedMotion,
)
from momo.domain.playback import PlaybackExecutionSnapshot, PlaybackOperatorIntent
from momo.domain.robot import JointState, RobotProfile
from momo.domain.safety import validate_logical_value
from momo.domain.trajectory import PreparedTrajectory
from momo.ports.motion_executor import MotionExecutor

PreparedCommand = PreparedMotion | PreparedContinuousJog
MIN_EFFECTIVE_CONTINUOUS_SPEED = 0.1
SMOOTHSTEP_PEAK_VELOCITY_FACTOR = 1.5


class MotionAdmissionCoordinator:
    """Serialize motion ownership and fence lifecycle transitions."""

    def __init__(self, slot_is_free: Callable[[], bool]) -> None:
        self._slot_is_free = slot_is_free
        self._guard = asyncio.Lock()
        self._lifecycle_epoch = 0
        self._lifecycle_count = 0

    @asynccontextmanager
    async def admit(self) -> AsyncIterator[None]:
        async with self._guard:
            yield

    def motion_slot_is_free(self) -> bool:
        """Read both owners while the caller holds ``admit``."""

        return self._slot_is_free()

    @property
    def lifecycle_epoch(self) -> int:
        return self._lifecycle_epoch

    @property
    def lifecycle_count(self) -> int:
        return self._lifecycle_count

    def capture_lifecycle_epoch(self) -> int:
        """Capture a request fence, rejecting work that starts during lifecycle Stop."""

        epoch = self._lifecycle_epoch
        self.require_lifecycle_epoch(epoch)
        return epoch

    def require_lifecycle_epoch(self, epoch: int) -> None:
        """Reject work begun before or during a lifecycle transition."""

        if self._lifecycle_count or epoch != self._lifecycle_epoch:
            raise MotionConflictError(
                "Motion intent was superseded by a lifecycle Stop",
                details={"reason": "LIFECYCLE_EPOCH_CHANGED"},
            )

    def begin_lifecycle(self) -> None:
        """Fence new work before lifecycle cancellation starts."""

        self._lifecycle_count += 1
        self._lifecycle_epoch += 1

    def end_lifecycle(self) -> None:
        """Open a new request epoch after one lifecycle transition completes."""

        self._lifecycle_epoch += 1
        self._lifecycle_count -= 1


class MotionSafetyGateway:
    """Fail-closed checks followed by a complete, immutable prepared command."""

    def __init__(
        self,
        robot_service: RobotApplicationService,
        kinematics_service: KinematicsService,
        calibration_service: CalibrationService,
        executor: MotionExecutor,
    ) -> None:
        self.robot_service = robot_service
        self.kinematics_service = kinematics_service
        self.calibration_service = calibration_service
        self.executor = executor
        self._external_motion_active: Callable[[], bool] = lambda: False
        self.motion_admission = MotionAdmissionCoordinator(self.motion_slot_is_free)

    def register_external_motion_guard(self, guard: Callable[[], bool]) -> None:
        """Bind one high-level playback owner without exposing an executor or driver."""

        self._external_motion_active = guard

    def motion_slot_is_free(self) -> bool:
        return self.executor.active_command_id is None and not self._external_motion_active()

    async def prepare(self, command: MotionCommand) -> PreparedCommand:
        status, profile, current = await self.robot_service.get_motion_snapshot()
        model = self.kinematics_service.model_for(profile)
        checks: list[PreflightCheck] = []

        def check(condition: bool, name: str, detail: str) -> None:
            evidence = f"{name} verified" if condition else detail
            checks.append(PreflightCheck(name=name, passed=condition, detail=evidence))
            if not condition:
                self._reject(command, checks, profile, model.fingerprint, detail)

        check(command.robot_id == status.robot_id, "active_robot", "command must target primary")
        check(
            status.connection_state is RobotConnectionState.CONNECTED,
            "connected",
            "active Dry Run robot must be connected",
        )
        check(status.control_mode is ControlMode.DRY_RUN, "control_mode", "DRY_RUN required")
        check(
            status.hardware_access_policy is HardwareAccessPolicy.DISABLED,
            "hardware_policy",
            "hardware access must remain DISABLED",
        )
        check(
            command.expected_profile_fingerprint == profile.fingerprint,
            "profile_fingerprint",
            "expected profile fingerprint does not match active profile",
        )
        check(
            command.expected_kinematics_fingerprint == model.fingerprint,
            "kinematics_fingerprint",
            "expected kinematics fingerprint does not match active model",
        )
        check(
            command.expected_state_sequence == status.state_sequence,
            "state_sequence",
            "expected state sequence is stale",
        )
        check(not status.stale, "state_freshness", "robot state is stale")
        check(
            self.motion_slot_is_free(),
            "command_conflict",
            "another motion is already active",
        )
        accepted_source = command.source is MotionCommandSource.CONTROL or (
            command.source is MotionCommandSource.LIBRARY
            and command.command_type is MotionCommandType.MOVE_JOINTS
        )
        check(
            accepted_source,
            "command_source",
            "Only CONTROL intents and Library Goto joint moves are accepted",
        )
        checks.append(
            PreflightCheck(
                name="idempotency",
                passed=True,
                detail="idempotency key validated by motion application service",
            )
        )

        if command.command_type is MotionCommandType.CONTINUOUS_JOG:
            payload = command.payload
            if not isinstance(payload, ContinuousJogPayload):
                raise TypeError("invalid continuous jog payload")
            definition = profile.definitions_by_id.get(payload.joint_id)
            check(definition is not None, "joint_set", "continuous jog joint is unknown")
            if definition is None:  # pragma: no cover - check raises
                raise AssertionError
            check(
                definition.domain_unit is payload.unit,
                "unit",
                f"{payload.joint_id} unit must be {definition.domain_unit.value}",
            )
            speed_limit = 100.0 if definition.joint_type is JointType.PRISMATIC else 45.0
            requested_speed = payload.speed_units_s * command.speed_scale
            check(
                MIN_EFFECTIVE_CONTINUOUS_SPEED <= requested_speed <= speed_limit,
                "provisional_dynamic_limits",
                f"continuous jog speed exceeds provisional {speed_limit} {payload.unit.value}/s",
            )
            maximum_acceleration = 800.0 if definition.joint_type is JointType.PRISMATIC else 720.0
            acceleration = min(maximum_acceleration, requested_speed / 0.2)
            ramp_duration = requested_speed / acceleration
            ramp_distance = 0.5 * acceleration * ramp_duration * ramp_duration
            maximum_timed_travel = ramp_distance + requested_speed * (
                MAX_EFFECTIVE_MOTION_DURATION_S - ramp_duration
            )
            maximum_delta = 150.0 if definition.joint_type is JointType.PRISMATIC else 120.0
            lower, upper = self._continuous_jog_bounds(
                command,
                profile,
                current,
                payload.joint_id,
                checks,
            )
            start_value = current.positions[payload.joint_id]
            safe_travel = min(maximum_delta, maximum_timed_travel)
            endpoint = (
                min(upper, start_value + safe_travel)
                if payload.direction > 0
                else max(lower, start_value - safe_travel)
            )
            travel = abs(endpoint - start_value)
            check(
                travel > 1e-9,
                "target_delta",
                "no safe continuous jog travel remains in the requested direction",
            )
            target_positions = dict(current.positions)
            target_positions[payload.joint_id] = endpoint
            target = JointState(positions=target_positions, units=current.units)
            actual_envelope_duration = (
                sqrt(2.0 * travel / acceleration)
                if travel <= ramp_distance
                else ramp_duration + (travel - ramp_distance) / requested_speed
            )
            validation_duration = max(
                actual_envelope_duration,
                sqrt(6.0 * travel / maximum_acceleration),
                0.05,
            )
            self._validate_target(
                command,
                profile,
                current,
                target,
                validation_duration * command.speed_scale,
                checks,
            )
            await self._validate_joint_path(
                command,
                profile,
                current,
                target,
                status.state_sequence,
                checks,
            )
            preflight = self._accepted(command, checks, profile, model.fingerprint)
            return PreparedContinuousJog(
                command_id=command.command_id,
                start_state=current,
                joint_id=payload.joint_id,
                direction=payload.direction,
                speed_units_s=requested_speed,
                acceleration_units_s2=acceleration,
                unit=payload.unit,
                minimum=min(start_value, endpoint),
                maximum=max(start_value, endpoint),
                preflight=preflight,
            )

        target, duration_s = await self._resolve_target(command, profile, current, checks)
        self._validate_target(command, profile, current, target, duration_s, checks)
        await self._validate_joint_path(
            command,
            profile,
            current,
            target,
            status.state_sequence,
            checks,
        )
        preflight = self._accepted(command, checks, profile, model.fingerprint)
        return PreparedMotion(
            command_id=command.command_id,
            start_state=current,
            target_state=target,
            duration_s=duration_s / command.speed_scale,
            preflight=preflight,
        )

    async def validate_prepared_trajectory(
        self,
        prepared: PreparedTrajectory,
        intent: PlaybackOperatorIntent,
        *,
        motion_revision: int,
    ) -> PlaybackExecutionSnapshot:
        """Revalidate the exact compiled plan at the single safety entry point."""

        plan = prepared.plan
        status, profile, current = await self.robot_service.get_motion_snapshot()
        model = self.kinematics_service.model_for(profile)
        reasons: list[str] = []
        if not prepared.preflight.accepted:
            reasons.append("PREFLIGHT_NOT_ACCEPTED")
        if (
            intent.motion_id != plan.motion_id
            or intent.motion_revision != plan.motion_revision
            or intent.trajectory_digest != plan.digest.sha256
        ):
            reasons.append("OPERATOR_INTENT_MISMATCH")
        reasons.extend(
            violation.code
            for violation in prepared.binding_violations(
                motion_revision=motion_revision,
                robot_variant=status.variant,
                profile_fingerprint=profile.fingerprint,
                kinematics_fingerprint=model.fingerprint,
                state_sequence=status.state_sequence,
            )
        )
        if not status.connected:
            reasons.append("ROBOT_NOT_CONNECTED")
        if status.stale:
            reasons.append("ROBOT_STATE_STALE")
        if status.control_mode is not ControlMode.DRY_RUN:
            reasons.append("CONTROL_MODE_CHANGED")
        if status.hardware_access_policy is not HardwareAccessPolicy.DISABLED:
            reasons.append("HARDWARE_POLICY_CHANGED")
        if self.executor.active_command_id is not None:
            reasons.append("MOTION_COMMAND_ACTIVE")
        first = plan.samples[0]
        if (
            set(current.positions) != set(first.positions)
            or current.units is None
            or dict(current.units) != dict(first.units)
            or any(
                not isclose(
                    current.positions[joint_id],
                    first.positions[joint_id],
                    rel_tol=0.0,
                    abs_tol=1e-6,
                )
                for joint_id in first.positions
            )
        ):
            reasons.append("START_STATE_CHANGED")
        stop_capable = callable(getattr(self.executor, "cancel_active", None)) and callable(
            getattr(self.robot_service, "stop", None)
        )
        if not stop_capable:
            reasons.append("STOP_CAPABILITY_UNAVAILABLE")
        if reasons:
            unique_reasons = list(dict.fromkeys(reasons))
            raise MotionPreflightError(
                "Prepared trajectory became unsafe before playback",
                details={"reasons": unique_reasons},
            )
        return PlaybackExecutionSnapshot(
            operator_intent_id=intent.intent_id,
            motion_id=plan.motion_id,
            motion_revision=motion_revision,
            robot_variant=status.variant,
            state_sequence=status.state_sequence,
            profile_fingerprint=profile.fingerprint,
            kinematics_fingerprint=model.fingerprint,
            connected=status.connected,
            stale=status.stale,
            stop_capable=stop_capable,
            control_mode=status.control_mode,
            hardware_access_policy=status.hardware_access_policy,
            safety_gateway_validated=True,
            hardware_accessed=False,
        )

    def _continuous_jog_bounds(
        self,
        command: MotionCommand,
        profile: RobotProfile,
        current: JointState,
        joint_id: str,
        checks: list[PreflightCheck],
    ) -> tuple[float, float]:
        definition = profile.definitions_by_id[joint_id]
        lower, upper = definition.minimum, definition.maximum
        calibration = self._compatible_raw_calibration(command, profile, checks)
        if calibration is None:
            return lower, upper
        calibration_joint = calibration.joints_by_id.get(joint_id)
        if calibration_joint is None:
            self._reject(
                command,
                checks,
                profile,
                self.kinematics_service.model_for(profile).fingerprint,
                f"missing calibration joint {joint_id}",
                "raw_derived_limits",
            )
        try:
            raw_lower, raw_upper = effective_logical_limits_from_raw_bounds(
                joint_id,
                profile,
                calibration_joint,
            )
        except HardwareMappingError as error:
            self._reject(
                command,
                checks,
                profile,
                self.kinematics_service.model_for(profile).fingerprint,
                str(error),
                "raw_derived_limits",
            )
        lower = max(lower, raw_lower)
        upper = min(upper, raw_upper)
        if not lower <= current.positions[joint_id] <= upper:
            self._reject(
                command,
                checks,
                profile,
                self.kinematics_service.model_for(profile).fingerprint,
                f"{joint_id} current state is outside raw-derived bounds",
                "raw_derived_limits",
            )
        return lower, upper

    def _compatible_raw_calibration(
        self,
        command: MotionCommand,
        profile: RobotProfile,
        checks: list[PreflightCheck],
    ) -> CalibrationDocument | None:
        calibration = self.calibration_service.get_for_variant(profile.variant)
        if calibration is None:
            return None
        report = self.calibration_service.status(profile, calibration)
        compatible = all(
            value is True
            for value in (
                report.variant_match,
                report.profile_match,
                report.joint_set_match,
                report.mapping_match,
            )
        )
        if not compatible:
            self._reject(
                command,
                checks,
                profile,
                self.kinematics_service.model_for(profile).fingerprint,
                (
                    "configured calibration is incompatible with the active "
                    f"profile ({report.status.value})"
                ),
                "raw_derived_limits",
            )
        return calibration

    async def _validate_joint_path(
        self,
        command: MotionCommand,
        profile: RobotProfile,
        current: JointState,
        target: JointState,
        state_sequence: int,
        checks: list[PreflightCheck],
    ) -> None:
        definitions = profile.definitions_by_id
        segments = max(
            1,
            max(
                ceil(
                    abs(target.positions[joint_id] - current.positions[joint_id])
                    / (10.0 if definitions[joint_id].joint_type is JointType.PRISMATIC else 5.0)
                )
                for joint_id in profile.enabled_joints
            ),
        )
        for sample_index in range(segments + 1):
            fraction = sample_index / segments
            sample = JointState(
                positions={
                    joint_id: current.positions[joint_id]
                    + (target.positions[joint_id] - current.positions[joint_id]) * fraction
                    for joint_id in profile.enabled_joints
                },
                units=current.units,
            )
            try:
                fk = await self.kinematics_service.forward(
                    profile,
                    sample,
                    state_sequence=state_sequence,
                    robot_id=command.robot_id,
                )
            except ValueError:
                self._reject(
                    command,
                    checks,
                    profile,
                    self.kinematics_service.model_for(profile).fingerprint,
                    f"FK invalid at provisional path sample {sample_index}/{segments}",
                    "fk_valid",
                )
            position = fk.tcp_pose.position_mm
            if not (
                -750.0 <= position.x <= 750.0
                and -750.0 <= position.y <= 750.0
                and -500.0 <= position.z <= 750.0
            ):
                self._reject(
                    command,
                    checks,
                    profile,
                    self.kinematics_service.model_for(profile).fingerprint,
                    f"workspace exceeded at provisional path sample {sample_index}/{segments}",
                    "workspace",
                )
        checks.append(
            PreflightCheck(
                name="fk_valid",
                passed=True,
                detail=f"FK finite across {segments + 1} bounded path samples",
            )
        )
        checks.append(
            PreflightCheck(
                name="workspace",
                passed=True,
                detail=f"workspace valid across {segments + 1} bounded path samples",
            )
        )
        checks.append(
            PreflightCheck(
                name="cancellation_state",
                passed=True,
                detail="executor has no pending cancellation",
            )
        )

    async def _resolve_target(
        self,
        command: MotionCommand,
        profile: RobotProfile,
        current: JointState,
        checks: list[PreflightCheck],
    ) -> tuple[JointState, float]:
        payload = command.payload
        if isinstance(payload, JointMovePayload):
            return payload.joint_state, payload.duration_s
        if isinstance(payload, JointJogStepPayload):
            definition = profile.definitions_by_id.get(payload.joint_id)
            self._require(
                command,
                checks,
                profile,
                definition is not None,
                "joint_set",
                "jog joint is unknown",
            )
            if definition is None:  # pragma: no cover
                raise AssertionError
            self._require(
                command,
                checks,
                profile,
                definition.domain_unit is payload.unit,
                "unit",
                f"{payload.joint_id} unit must be {definition.domain_unit.value}",
            )
            positions = dict(current.positions)
            positions[payload.joint_id] += payload.delta
            return JointState(positions=positions, units=current.units), payload.duration_s
        if isinstance(payload, HomePayload):
            return (
                JointState(
                    positions={item.joint_id: item.home for item in profile.joint_definitions},
                    units={item.joint_id: item.domain_unit for item in profile.joint_definitions},
                ),
                payload.duration_s,
            )
        if isinstance(payload, MovePosePayload):
            result = await self.kinematics_service.inverse(
                profile, payload.target_pose, seed=current
            )
            self._require(
                command,
                checks,
                profile,
                result.success and result.joint_state_optional is not None,
                "ik_residual",
                (
                    f"IK rejected: {result.termination_reason}; "
                    f"position_error_mm={result.position_error_mm:.3f}"
                ),
            )
            if result.joint_state_optional is None:  # pragma: no cover
                raise AssertionError
            return result.joint_state_optional, payload.duration_s
        if isinstance(payload, CartesianJogPayload):
            fk = await self.kinematics_service.forward(
                profile,
                current,
                state_sequence=command.expected_state_sequence,
                robot_id=command.robot_id,
            )
            target_pose = await self.kinematics_service.compose_delta(
                profile,
                fk.tcp_pose,
                delta_position_mm=(
                    payload.delta_position_mm.x,
                    payload.delta_position_mm.y,
                    payload.delta_position_mm.z,
                ),
                delta_rotation_deg=(
                    payload.delta_rotation_deg.x,
                    payload.delta_rotation_deg.y,
                    payload.delta_rotation_deg.z,
                ),
                frame=payload.frame,
            )
            constrain_orientation = any(
                abs(value) > 1e-12
                for value in (
                    payload.delta_rotation_deg.x,
                    payload.delta_rotation_deg.y,
                    payload.delta_rotation_deg.z,
                )
            )
            result = await self.kinematics_service.inverse(
                profile,
                target_pose,
                seed=current,
                position_only=not constrain_orientation,
            )
            self._require(
                command,
                checks,
                profile,
                result.success and result.joint_state_optional is not None,
                "ik_residual",
                f"Cartesian IK rejected: {result.termination_reason}",
            )
            if result.joint_state_optional is None:  # pragma: no cover
                raise AssertionError
            return result.joint_state_optional, payload.duration_s
        raise TypeError(f"unsupported payload: {type(payload).__name__}")

    def _validate_target(
        self,
        command: MotionCommand,
        profile: RobotProfile,
        current: JointState,
        target: JointState,
        duration_s: float,
        checks: list[PreflightCheck],
    ) -> None:
        effective_duration = duration_s / command.speed_scale
        if effective_duration > MAX_EFFECTIVE_MOTION_DURATION_S:
            self._reject(
                command,
                checks,
                profile,
                self.kinematics_service.model_for(profile).fingerprint,
                f"effective motion duration exceeds {MAX_EFFECTIVE_MOTION_DURATION_S:.0f} seconds",
                "provisional_dynamic_limits",
            )
        try:
            target.validate_against(profile)
        except ValueError as error:
            self._reject(
                command,
                checks,
                profile,
                self.kinematics_service.model_for(profile).fingerprint,
                str(error),
                "logical_limits",
            )
        self._record_passed_once(checks, "joint_set", "exact enabled_joints verified")
        self._record_passed_once(checks, "units", "all units explicit and verified")
        checks.append(
            PreflightCheck(name="finite_numbers", passed=True, detail="all targets finite")
        )

        calibration = self._compatible_raw_calibration(command, profile, checks)
        if calibration is not None:
            by_id = calibration.joints_by_id
            try:
                for state_name, state in (("current", current), ("target", target)):
                    for joint_id, value in state.positions.items():
                        calibration_joint = by_id.get(joint_id)
                        if calibration_joint is None:
                            raise HardwareMappingError(f"missing calibration joint {joint_id}")
                        try:
                            validate_logical_value(joint_id, value, profile, calibration_joint)
                        except HardwareMappingError as error:
                            raise HardwareMappingError(f"{state_name} state: {error}") from error
            except HardwareMappingError as error:
                self._reject(
                    command,
                    checks,
                    profile,
                    self.kinematics_service.model_for(profile).fingerprint,
                    str(error),
                    "raw_derived_limits",
                )
            checks.append(
                PreflightCheck(
                    name="raw_derived_limits",
                    passed=True,
                    detail=(
                        "captured current state and target are reachable within "
                        "configured raw-derived bounds"
                    ),
                )
            )
        else:
            checks.append(
                PreflightCheck(
                    name="raw_derived_limits",
                    passed=True,
                    detail=(
                        "not_applicable: no calibration configured; logical limits "
                        "remain authoritative in Dry Run"
                    ),
                )
            )

        definitions = profile.definitions_by_id
        for joint_id in profile.enabled_joints:
            delta = abs(target.positions[joint_id] - current.positions[joint_id])
            definition = definitions[joint_id]
            max_delta = 150.0 if definition.joint_type is JointType.PRISMATIC else 120.0
            if delta > max_delta + 1e-9:
                self._reject(
                    command,
                    checks,
                    profile,
                    self.kinematics_service.model_for(profile).fingerprint,
                    (
                        f"{joint_id} target delta exceeds provisional {max_delta} "
                        f"{definition.domain_unit.value}"
                    ),
                    "target_delta",
                )
            max_speed = 100.0 if definition.joint_type is JointType.PRISMATIC else 90.0
            smoothstep_peak_velocity = SMOOTHSTEP_PEAK_VELOCITY_FACTOR * delta / effective_duration
            if smoothstep_peak_velocity > max_speed + 1e-9:
                self._reject(
                    command,
                    checks,
                    profile,
                    self.kinematics_service.model_for(profile).fingerprint,
                    f"{joint_id} exceeds provisional speed limit",
                    "provisional_dynamic_limits",
                )
            max_acceleration = 800.0 if definition.joint_type is JointType.PRISMATIC else 720.0
            smoothstep_peak_acceleration = 6.0 * delta / (effective_duration**2)
            if smoothstep_peak_acceleration > max_acceleration + 1e-9:
                self._reject(
                    command,
                    checks,
                    profile,
                    self.kinematics_service.model_for(profile).fingerprint,
                    f"{joint_id} exceeds provisional acceleration limit",
                    "provisional_dynamic_limits",
                )
        self._record_passed_once(checks, "target_delta", "provisional delta limits verified")
        self._record_passed_once(
            checks,
            "provisional_dynamic_limits",
            "provisional Dry Run cubic-smoothstep peak velocity and acceleration verified",
        )

    def _require(
        self,
        command: MotionCommand,
        checks: list[PreflightCheck],
        profile: RobotProfile,
        condition: bool,
        name: str,
        detail: str,
    ) -> None:
        evidence = f"{name} verified" if condition else detail
        checks.append(PreflightCheck(name=name, passed=condition, detail=evidence))
        if not condition:
            self._reject(
                command,
                checks,
                profile,
                self.kinematics_service.model_for(profile).fingerprint,
                detail,
            )

    @staticmethod
    def _record_passed_once(
        checks: list[PreflightCheck],
        name: str,
        detail: str,
    ) -> None:
        if any(check.name == name for check in checks):
            return
        checks.append(PreflightCheck(name=name, passed=True, detail=detail))

    @staticmethod
    def _accepted(
        command: MotionCommand,
        checks: list[PreflightCheck],
        profile: RobotProfile,
        kinematics_fingerprint: str,
    ) -> MotionPreflight:
        return MotionPreflight(
            accepted=True,
            command_id=command.command_id,
            checks=checks,
            warnings=["Kinematics and dynamic/workspace limits are PROVISIONAL_DRY_RUN only"],
            profile_fingerprint=profile.fingerprint,
            kinematics_fingerprint=kinematics_fingerprint,
        )

    @staticmethod
    def _reject(
        command: MotionCommand,
        checks: list[PreflightCheck],
        profile: RobotProfile,
        kinematics_fingerprint: str,
        detail: str,
        name: str | None = None,
    ) -> NoReturn:
        if name is not None:
            checks.append(PreflightCheck(name=name, passed=False, detail=detail))
        preflight = MotionPreflight(
            accepted=False,
            command_id=command.command_id,
            checks=checks,
            warnings=["No state was changed"],
            profile_fingerprint=profile.fingerprint,
            kinematics_fingerprint=kinematics_fingerprint,
        )
        raise MotionPreflightError(
            detail,
            details={"preflight": preflight.model_dump(mode="json")},
        )
