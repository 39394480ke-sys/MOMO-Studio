"""Domain-specific validation failures."""


class DomainValidationError(ValueError):
    """Base class for an invariant violation in a domain value."""


class JointStateValidationError(DomainValidationError):
    """A joint state cannot be interpreted using the supplied robot profile."""


class ProfileResolutionError(DomainValidationError):
    """An explicit entity-validation profile is missing, malformed, or mismatched."""


class RobotApplicationError(RuntimeError):
    """Safe, structured application failure exposed by the HTTP boundary."""

    code = "INTERNAL_ERROR"
    status_code = 500

    def __init__(self, message: str, *, details: object | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class RobotAlreadyConnectedError(RobotApplicationError):
    code = "ROBOT_ALREADY_CONNECTED"
    status_code = 409


class RobotNotConnectedError(RobotApplicationError):
    code = "ROBOT_NOT_CONNECTED"
    status_code = 409


class RobotBusyError(RobotApplicationError):
    code = "ROBOT_BUSY"
    status_code = 409


class VariantSwitchWhileConnectedError(RobotApplicationError):
    code = "VARIANT_SWITCH_WHILE_CONNECTED"
    status_code = 409


class ProfileInvalidError(RobotApplicationError):
    code = "PROFILE_INVALID"
    status_code = 422


class CalibrationInvalidError(RobotApplicationError):
    code = "CALIBRATION_INVALID"
    status_code = 422


class HardwareAccessDisabledError(RobotApplicationError):
    code = "HARDWARE_ACCESS_DISABLED"
    status_code = 403


class RuntimeStateInvalidError(RobotApplicationError):
    code = "RUNTIME_STATE_INVALID"
    status_code = 422


class MotionPreflightError(RobotApplicationError):
    code = "MOTION_PREFLIGHT_REJECTED"
    status_code = 422


class MotionConflictError(RobotApplicationError):
    code = "MOTION_CONFLICT"
    status_code = 409


class MotionCommandNotFoundError(RobotApplicationError):
    code = "MOTION_COMMAND_NOT_FOUND"
    status_code = 404


class IdempotencyConflictError(RobotApplicationError):
    code = "IDEMPOTENCY_CONFLICT"
    status_code = 409


class JogSessionNotFoundError(RobotApplicationError):
    code = "JOG_SESSION_NOT_FOUND"
    status_code = 404


class JogLeaseExpiredError(RobotApplicationError):
    code = "JOG_LEASE_EXPIRED"
    status_code = 409


class EntityNotFoundError(RobotApplicationError):
    code = "ENTITY_NOT_FOUND"
    status_code = 404


class EntityAlreadyExistsError(RobotApplicationError):
    code = "ENTITY_ALREADY_EXISTS"
    status_code = 409


class RevisionConflictError(RobotApplicationError):
    code = "REVISION_CONFLICT"
    status_code = 409


class EntityInvalidError(RobotApplicationError):
    code = "ENTITY_INVALID"
    status_code = 422


class RepositoryCapacityError(RobotApplicationError):
    code = "REPOSITORY_CAPACITY_EXCEEDED"
    status_code = 507


class CaptureStateChangedError(RobotApplicationError):
    code = "CAPTURE_STATE_CHANGED"
    status_code = 409


class PoseIncompatibleError(RobotApplicationError):
    code = "POSE_INCOMPATIBLE"
    status_code = 422


class PreparedTrajectoryNotFoundError(RobotApplicationError):
    code = "PREPARED_TRAJECTORY_NOT_FOUND"
    status_code = 404


class HardwareMappingError(DomainValidationError):
    """A logical/raw conversion cannot be proven valid from explicit inputs."""
