"""Domain-specific validation failures."""


class DomainValidationError(ValueError):
    """Base class for an invariant violation in a domain value."""


class JointStateValidationError(DomainValidationError):
    """A joint state cannot be interpreted using the supplied robot profile."""


class ProfileResolutionError(DomainValidationError):
    """An explicit entity-validation profile is missing, malformed, or mismatched."""
