"""Hardware-facing adapters; Stage 2 exports only the in-memory Dry Run driver."""

from momo.adapters.hardware.dry_run_robot_driver import DryRunRobotDriver

__all__ = ["DryRunRobotDriver"]
