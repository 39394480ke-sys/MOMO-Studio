"""Stable product enumerations used by the domain and API contracts."""

from enum import StrEnum


class RobotVariant(StrEnum):
    """A product variant, not a software version."""

    V1 = "V1"
    V2 = "V2"


class ControlMode(StrEnum):
    """User-visible robot control modes.

    A fake adapter may be used by tests, but SIM is intentionally not a product mode.
    """

    DRY_RUN = "DRY_RUN"
    REAL = "REAL"


class HardwareAccessPolicy(StrEnum):
    """Capability gate for hardware adapters.

    Stage 2 accepts only ``DISABLED``.  The other values remain part of the
    contract so a later stage can add reviewed read-only/full adapters without
    changing the domain vocabulary.
    """

    DISABLED = "DISABLED"
    READ_ONLY = "READ_ONLY"
    FULL = "FULL"


class ProfileVerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED_FOR_DRY_RUN = "VERIFIED_FOR_DRY_RUN"
    VERIFIED_FOR_REAL = "VERIFIED_FOR_REAL"


class KinematicsVerificationStatus(StrEnum):
    """How far a kinematics model has been independently verified."""

    PROVISIONAL_DRY_RUN = "PROVISIONAL_DRY_RUN"
    VERIFIED_FOR_DRY_RUN = "VERIFIED_FOR_DRY_RUN"
    VERIFIED_FOR_REAL = "VERIFIED_FOR_REAL"


class RobotConnectionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DISCONNECTING = "DISCONNECTING"
    FAULTED = "FAULTED"


class CalibrationOperatingMode(StrEnum):
    MULTI_TURN = "MULTI_TURN"
    SINGLE_TURN = "SINGLE_TURN"


class CalibrationStatus(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    TEMPLATE_ONLY = "TEMPLATE_ONLY"
    VARIANT_MISMATCH = "VARIANT_MISMATCH"
    PROFILE_MISMATCH = "PROFILE_MISMATCH"
    JOINT_SET_MISMATCH = "JOINT_SET_MISMATCH"
    INCOMPLETE = "INCOMPLETE"
    VALID_FOR_DRY_RUN = "VALID_FOR_DRY_RUN"
    READY_FOR_REAL = "READY_FOR_REAL"


class RealReadiness(StrEnum):
    BLOCKED_BY_STAGE_POLICY = "BLOCKED_BY_STAGE_POLICY"
    READY = "READY"


class StopResult(StrEnum):
    STOPPED = "STOPPED"
    NOT_CONNECTED = "NOT_CONNECTED"
    FAILED = "FAILED"
    SAFETY_STATE_UNCERTAIN = "SAFETY_STATE_UNCERTAIN"


class JointType(StrEnum):
    REVOLUTE = "REVOLUTE"
    PRISMATIC = "PRISMATIC"


class DomainUnit(StrEnum):
    """Canonical persisted units at the domain/UI boundary."""

    DEG = "deg"
    MM = "mm"


class MotionMode(StrEnum):
    JOINT = "JOINT"
    CARTESIAN_LINEAR = "CARTESIAN_LINEAR"


class Easing(StrEnum):
    LINEAR = "LINEAR"
    SMOOTHSTEP = "SMOOTHSTEP"
    EASE_IN_OUT = "EASE_IN_OUT"


class CartesianFrame(StrEnum):
    BASE = "BASE"
    TOOL = "TOOL"


class MotionCommandSource(StrEnum):
    CONTROL = "CONTROL"
    LIBRARY = "LIBRARY"
    STUDIO = "STUDIO"
    PLAYBACK = "PLAYBACK"
    VISION = "VISION"
    SYSTEM = "SYSTEM"


class MotionCommandType(StrEnum):
    MOVE_JOINTS = "MOVE_JOINTS"
    JOINT_JOG_STEP = "JOINT_JOG_STEP"
    CONTINUOUS_JOG = "CONTINUOUS_JOG"
    CARTESIAN_JOG = "CARTESIAN_JOG"
    MOVE_POSE = "MOVE_POSE"
    HOME = "HOME"


class MotionCommandState(StrEnum):
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAULTED = "FAULTED"
