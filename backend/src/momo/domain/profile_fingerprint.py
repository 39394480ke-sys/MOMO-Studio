"""Deterministic identity for the safety-relevant portion of a robot profile."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from momo.domain.robot import RobotProfile


def canonical_profile_payload(profile: RobotProfile) -> dict[str, Any]:
    """Return only fields that can change motion, mapping, or safety behavior."""

    return {
        "variant": profile.variant.value,
        "enabled_joints": list(profile.enabled_joints),
        "joints": [
            {
                "joint_id": definition.joint_id,
                "joint_type": definition.joint_type.value,
                "domain_unit": definition.domain_unit.value,
                "servo_id": definition.servo_id,
                "motor_degrees_per_domain_unit": definition.motor_degrees_per_domain_unit,
                "raw_counts_per_motor_revolution": definition.raw_counts_per_motor_revolution,
                "operating_mode": definition.operating_mode.value,
                "direction": definition.direction,
                "minimum": definition.minimum,
                "maximum": definition.maximum,
                "home": definition.home,
                "home_present_raw": definition.home_present_raw,
                "raw_bounds": (
                    list(definition.raw_bounds) if definition.raw_bounds is not None else None
                ),
                "raw_reachable": definition.raw_reachable,
            }
            for definition in profile.joint_definitions
        ],
    }


def profile_fingerprint(profile: RobotProfile) -> str:
    canonical = json.dumps(
        canonical_profile_payload(profile),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
