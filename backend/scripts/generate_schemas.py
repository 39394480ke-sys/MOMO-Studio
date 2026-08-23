"""Generate deterministic JSON Schema artifacts from the Pydantic domain models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import BaseModel

from momo.domain.calibration import CalibrationDocument
from momo.domain.kinematics.model import KinematicsModel
from momo.domain.motion import Motion
from momo.domain.pose import Pose
from momo.domain.robot import RobotProfile
from momo.domain.runtime import RobotStatus, RuntimeState

SCHEMAS: dict[str, type[BaseModel]] = {
    "calibration.schema.json": CalibrationDocument,
    "kinematics-model.schema.json": KinematicsModel,
    "motion.schema.json": Motion,
    "pose.schema.json": Pose,
    "robot-profile.schema.json": RobotProfile,
    "robot-status.schema.json": RobotStatus,
    "runtime-state.schema.json": RuntimeState,
}


def default_output_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "schemas"


def generate_schemas(output_directory: Path) -> list[Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for filename, model in sorted(SCHEMAS.items()):
        destination = output_directory / filename
        schema = model.model_json_schema(mode="serialization")
        destination.write_text(
            json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        generated.append(destination)
    return generated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output_directory(),
        help="schema output directory",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path in generate_schemas(args.output_dir):
        print(path)


if __name__ == "__main__":
    main()
