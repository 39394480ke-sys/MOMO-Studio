"""Shared synthetic Stage 2 fixtures with no device-local inputs."""

from typing import cast

from momo.domain.calibration import CalibrationDocument, CalibrationJoint
from momo.domain.enums import CalibrationOperatingMode
from momo.domain.robot import RobotProfile


def make_calibration(
    profile: RobotProfile,
    *,
    template: bool = False,
) -> CalibrationDocument:
    """Build a complete synthetic calibration tied to an explicit profile."""

    return CalibrationDocument(
        robot_variant=profile.variant,
        profile_fingerprint=profile.fingerprint,
        template=template,
        notes="Synthetic test fixture; never a real calibration.",
        joints=[
            CalibrationJoint(
                joint_id=definition.joint_id,
                servo_id=cast(int, definition.servo_id),
                operating_mode=CalibrationOperatingMode.MULTI_TURN,
                direction=1,
                home_present_raw=0,
                phase=0,
                raw_bounds=(-30719, 30719),
            )
            for definition in profile.joint_definitions
        ],
    )
