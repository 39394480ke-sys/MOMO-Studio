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
