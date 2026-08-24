"""Isolated Stage 6 app fixtures; all robot behavior remains Dry Run."""

from pathlib import Path

from fastapi import FastAPI

from momo.api.app import create_app
from momo.settings import Settings


def make_stage6_app(tmp_path: Path) -> FastAPI:
    return create_app(
        Settings(
            runtime_state_directory=str(tmp_path / "runtime"),
            pose_directory=str(tmp_path / "poses"),
            motion_library_directory=str(tmp_path / "motions"),
            motion_draft_directory=str(tmp_path / "drafts"),
            calibration_directory=str(tmp_path / "no-calibration"),
        )
    )
