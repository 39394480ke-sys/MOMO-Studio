"""Deterministic NumPy serial-chain FK and damped-least-squares IK."""

from __future__ import annotations

from math import acos, cos, isfinite, sin

import numpy as np
from numpy.typing import NDArray

from momo.domain.enums import CartesianFrame, JointType
from momo.domain.kinematics.model import KinematicsModel
from momo.ports.kinematics import (
    KinematicsInverseResult,
    KinematicsJointState,
    KinematicsTcpPose,
)

Matrix = NDArray[np.float64]


def _quaternion_to_matrix(quaternion: tuple[float, float, float, float]) -> Matrix:
    q = np.asarray(quaternion, dtype=np.float64)
    if q.shape != (4,):
        raise ValueError("quaternion must contain exactly four XYZW components")
    norm = float(np.linalg.norm(q))
    if not isfinite(norm) or norm < 1e-12:
        raise ValueError("quaternion must be finite and non-zero")
    x, y, z, w = q / norm
    return np.asarray(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _matrix_to_quaternion(matrix: Matrix) -> tuple[float, float, float, float]:
    rotation = np.asarray(matrix, dtype=np.float64).reshape(3, 3)
    trace = float(np.trace(rotation))
    if trace > 0:
        scale = 2.0 * np.sqrt(trace + 1.0)
        w = 0.25 * scale
        x = (rotation[2, 1] - rotation[1, 2]) / scale
        y = (rotation[0, 2] - rotation[2, 0]) / scale
        z = (rotation[1, 0] - rotation[0, 1]) / scale
    else:
        index = int(np.argmax(np.diag(rotation)))
        if index == 0:
            scale = 2.0 * np.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2])
            x = 0.25 * scale
            y = (rotation[0, 1] + rotation[1, 0]) / scale
            z = (rotation[0, 2] + rotation[2, 0]) / scale
            w = (rotation[2, 1] - rotation[1, 2]) / scale
        elif index == 1:
            scale = 2.0 * np.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2])
            x = (rotation[0, 1] + rotation[1, 0]) / scale
            y = 0.25 * scale
            z = (rotation[1, 2] + rotation[2, 1]) / scale
            w = (rotation[0, 2] - rotation[2, 0]) / scale
        else:
            scale = 2.0 * np.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1])
            x = (rotation[0, 2] + rotation[2, 0]) / scale
            y = (rotation[1, 2] + rotation[2, 1]) / scale
            z = 0.25 * scale
            w = (rotation[1, 0] - rotation[0, 1]) / scale
    result = np.asarray([x, y, z, w], dtype=np.float64)
    result /= np.linalg.norm(result)
    if result[3] < 0 or (
        abs(float(result[3])) < 1e-15
        and next((float(item) for item in result[:3] if abs(float(item)) > 1e-15), 1.0) < 0
    ):
        result *= -1
    return tuple(float(item) for item in result)  # type: ignore[return-value]


def _axis_angle(axis: tuple[float, float, float], angle: float) -> Matrix:
    unit = np.asarray(axis, dtype=np.float64)
    unit /= np.linalg.norm(unit)
    x, y, z = unit
    skew = np.asarray([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    identity = np.eye(3, dtype=np.float64)
    return np.asarray(
        identity + sin(angle) * skew + (1.0 - cos(angle)) * (skew @ skew),
        dtype=np.float64,
    )


def _rpy_matrix(roll: float, pitch: float, yaw: float) -> Matrix:
    rx = _axis_angle((1.0, 0.0, 0.0), roll)
    ry = _axis_angle((0.0, 1.0, 0.0), pitch)
    rz = _axis_angle((0.0, 0.0, 1.0), yaw)
    return rz @ ry @ rx


def _rotation_error(target: Matrix, current: Matrix) -> NDArray[np.float64]:
    relative = target @ current.T
    cosine = float(np.clip((np.trace(relative) - 1.0) / 2.0, -1.0, 1.0))
    angle = acos(cosine)
    if angle < 1e-10:
        return np.zeros(3, dtype=np.float64)
    if abs(angle - np.pi) < 1e-6:
        diagonal = np.maximum((np.diag(relative) + 1.0) / 2.0, 0.0)
        axis = np.sqrt(diagonal)
        axis[0] = np.copysign(axis[0], relative[2, 1] - relative[1, 2] or 1.0)
        axis[1] = np.copysign(axis[1], relative[0, 2] - relative[2, 0] or 1.0)
        axis[2] = np.copysign(axis[2], relative[1, 0] - relative[0, 1] or 1.0)
        norm = float(np.linalg.norm(axis))
        return axis / norm * angle if norm > 1e-12 else np.asarray([angle, 0.0, 0.0])
    vector = np.asarray(
        [
            relative[2, 1] - relative[1, 2],
            relative[0, 2] - relative[2, 0],
            relative[1, 0] - relative[0, 1],
        ],
        dtype=np.float64,
    )
    return vector * (angle / (2.0 * sin(angle)))


def compose_delta_pose(
    current: KinematicsTcpPose,
    delta_position_m: tuple[float, float, float],
    delta_rpy_rad: tuple[float, float, float],
    frame: CartesianFrame,
) -> KinematicsTcpPose:
    current_position = np.asarray(current.position_m, dtype=np.float64)
    delta_position = np.asarray(delta_position_m, dtype=np.float64)
    delta_rpy = np.asarray(delta_rpy_rad, dtype=np.float64)
    if (
        current_position.shape != (3,)
        or delta_position.shape != (3,)
        or delta_rpy.shape != (3,)
        or not np.all(np.isfinite(current_position))
        or not np.all(np.isfinite(delta_position))
        or not np.all(np.isfinite(delta_rpy))
    ):
        raise ValueError("Cartesian pose and delta values must be finite three-vectors")
    current_rotation = _quaternion_to_matrix(current.orientation_quaternion_xyzw)
    delta_rotation = _rpy_matrix(*tuple(float(value) for value in delta_rpy))
    if frame is CartesianFrame.TOOL:
        target_position = current_position + current_rotation @ delta_position
        target_rotation = current_rotation @ delta_rotation
    else:
        target_position = current_position + delta_position
        target_rotation = delta_rotation @ current_rotation
    return KinematicsTcpPose(
        frame=current.frame,
        position_m=tuple(float(item) for item in target_position),  # type: ignore[arg-type]
        orientation_quaternion_xyzw=_matrix_to_quaternion(target_rotation),
    )


class SerialChainKinematics:
    """Pure numerical adapter: no mesh, GUI, device, thread, or filesystem access."""

    def compose_delta(
        self,
        current: KinematicsTcpPose,
        delta_position_m: tuple[float, float, float],
        delta_rpy_rad: tuple[float, float, float],
        frame: CartesianFrame,
    ) -> KinematicsTcpPose:
        return compose_delta_pose(current, delta_position_m, delta_rpy_rad, frame)

    @staticmethod
    def _ordered_values(model: KinematicsModel, joints: KinematicsJointState) -> Matrix:
        expected = {joint.joint_id for joint in model.joints}
        actual = set(joints.positions_si)
        if actual != expected:
            raise ValueError(
                f"kinematics joint set mismatch; missing={sorted(expected - actual)}, "
                f"unknown={sorted(actual - expected)}"
            )
        values = np.asarray(
            [joints.positions_si[joint.joint_id] for joint in model.joints],
            dtype=np.float64,
        )
        if not np.all(np.isfinite(values)):
            raise ValueError("kinematics joint values must be finite")
        for index, joint in enumerate(model.joints):
            if not joint.minimum_si <= values[index] <= joint.maximum_si:
                raise ValueError(f"{joint.joint_id} is outside kinematics limits")
        return values

    @staticmethod
    def _forward_matrix(model: KinematicsModel, values: Matrix) -> Matrix:
        transform = np.eye(4, dtype=np.float64)
        for index, joint in enumerate(model.joints):
            origin = np.eye(4, dtype=np.float64)
            origin[:3, :3] = _quaternion_to_matrix(joint.origin_orientation_quaternion_xyzw)
            origin[:3, 3] = np.asarray(joint.origin_translation_m, dtype=np.float64)
            motion = np.eye(4, dtype=np.float64)
            if joint.joint_type is JointType.REVOLUTE:
                motion[:3, :3] = _axis_angle(joint.axis, float(values[index]))
            else:
                motion[:3, 3] = np.asarray(joint.axis) * float(values[index])
            transform = transform @ origin @ motion
        return transform

    async def forward(
        self,
        model: KinematicsModel,
        joints: KinematicsJointState,
    ) -> KinematicsTcpPose:
        values = self._ordered_values(model, joints)
        transform = self._forward_matrix(model, values)
        return KinematicsTcpPose(
            frame=model.base_frame,
            position_m=tuple(float(item) for item in transform[:3, 3]),  # type: ignore[arg-type]
            orientation_quaternion_xyzw=_matrix_to_quaternion(transform[:3, :3]),
        )

    async def inverse(
        self,
        model: KinematicsModel,
        target: KinematicsTcpPose,
        seed: KinematicsJointState | None = None,
        *,
        position_only: bool = False,
        maximum_iterations: int = 200,
        position_tolerance_m: float = 0.001,
        orientation_tolerance_rad: float = 0.02,
    ) -> KinematicsInverseResult:
        if target.frame != model.base_frame:
            return KinematicsInverseResult(
                False, None, None, 0, 1e9, None, "INVALID_TARGET", ("frame mismatch",)
            )
        target_position = np.asarray(target.position_m, dtype=np.float64)
        if target_position.shape != (3,) or not np.all(np.isfinite(target_position)):
            return KinematicsInverseResult(
                False, None, None, 0, 1e9, None, "INVALID_TARGET", ("invalid position",)
            )
        if float(np.max(np.abs(target_position))) > 1e6:
            return KinematicsInverseResult(
                False,
                None,
                None,
                0,
                1e9,
                None,
                "INVALID_TARGET",
                ("position exceeds numerical safety bound",),
            )
        try:
            target_rotation = _quaternion_to_matrix(target.orientation_quaternion_xyzw)
        except ValueError:
            return KinematicsInverseResult(
                False, None, None, 0, 1e9, None, "INVALID_TARGET", ("invalid quaternion",)
            )

        if seed is None:
            values = np.asarray(
                [(joint.minimum_si + joint.maximum_si) / 2.0 for joint in model.joints],
                dtype=np.float64,
            )
        else:
            try:
                values = self._ordered_values(model, seed)
            except ValueError as seed_error:
                return KinematicsInverseResult(
                    False, None, None, 0, 1e9, None, "INVALID_SEED", (str(seed_error),)
                )
        lower = np.asarray([joint.minimum_si for joint in model.joints], dtype=np.float64)
        upper = np.asarray([joint.maximum_si for joint in model.joints], dtype=np.float64)
        damping = 1e-2
        best_values = values.copy()
        best_norm = float("inf")
        best_position_error = float("inf")
        best_orientation_error: float | None = None
        stalled = 0
        iterations = 0

        def evaluate(candidate: Matrix) -> tuple[Matrix, float, float | None, Matrix]:
            transform = self._forward_matrix(model, candidate)
            position_error_vector = target_position - transform[:3, 3]
            position_error = float(np.linalg.norm(position_error_vector))
            if position_only:
                return position_error_vector, position_error, None, transform
            orientation_vector = _rotation_error(target_rotation, transform[:3, :3])
            orientation_error = float(np.linalg.norm(orientation_vector))
            return (
                np.concatenate((position_error_vector, orientation_vector)),
                position_error,
                orientation_error,
                transform,
            )

        for iteration in range(1, max(1, maximum_iterations) + 1):
            iterations = iteration
            residual, position_error, orientation_error, _ = evaluate(values)
            error_norm = float(np.linalg.norm(residual))
            if error_norm < best_norm:
                best_norm = error_norm
                best_values = values.copy()
                best_position_error = position_error
                best_orientation_error = orientation_error
            orientation_ok = position_only or (
                orientation_error is not None and orientation_error <= orientation_tolerance_rad
            )
            if position_error <= position_tolerance_m and orientation_ok:
                solution = KinematicsJointState(
                    positions_si={
                        joint.joint_id: float(values[index])
                        for index, joint in enumerate(model.joints)
                    }
                )
                return KinematicsInverseResult(
                    True,
                    solution,
                    solution,
                    iterations,
                    position_error,
                    orientation_error,
                    "CONVERGED",
                )

            rows = 3 if position_only else 6
            jacobian = np.zeros((rows, len(model.joints)), dtype=np.float64)
            for index, _joint in enumerate(model.joints):
                epsilon = 1e-6
                perturbed = values.copy()
                perturbed[index] = min(upper[index], values[index] + epsilon)
                actual_step = float(perturbed[index] - values[index])
                if actual_step <= 1e-12:
                    perturbed[index] = max(lower[index], values[index] - epsilon)
                    actual_step = float(perturbed[index] - values[index])
                if abs(actual_step) <= 1e-12:
                    continue
                current_transform = self._forward_matrix(model, values)
                perturbed_transform = self._forward_matrix(model, perturbed)
                jacobian[:3, index] = (
                    perturbed_transform[:3, 3] - current_transform[:3, 3]
                ) / actual_step
                if not position_only:
                    jacobian[3:, index] = (
                        _rotation_error(perturbed_transform[:3, :3], current_transform[:3, :3])
                        / actual_step
                    )
            regularized = jacobian @ jacobian.T + (damping * damping) * np.eye(rows)
            try:
                delta = jacobian.T @ np.linalg.solve(regularized, residual)
            except np.linalg.LinAlgError:
                damping = min(1.0, damping * 10.0)
                stalled += 1
                if stalled >= 8:
                    break
                continue
            for index, joint in enumerate(model.joints):
                maximum_step = 0.01 if joint.joint_type is JointType.PRISMATIC else 0.15
                delta[index] = float(np.clip(delta[index], -maximum_step, maximum_step))
            candidate = np.clip(values + delta, lower, upper)
            candidate_error, _, _, _ = evaluate(candidate)
            if float(np.linalg.norm(candidate_error)) + 1e-12 < error_norm:
                values = candidate
                damping = max(1e-5, damping * 0.6)
                stalled = 0
            else:
                damping = min(1.0, damping * 4.0)
                stalled += 1
                if stalled >= 12:
                    break

        best = KinematicsJointState(
            positions_si={
                joint.joint_id: float(best_values[index])
                for index, joint in enumerate(model.joints)
            }
        )
        return KinematicsInverseResult(
            False,
            None,
            best,
            iterations,
            best_position_error,
            best_orientation_error,
            "STALLED" if stalled >= 12 else "MAX_ITERATIONS",
            ("best effort only; target did not converge",),
        )
