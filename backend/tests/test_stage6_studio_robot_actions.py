"""Direct tests for Studio's lock-free live robot actions."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI

from momo.application.services.motion_service import MotionApplicationService
from momo.application.services.studio_robot_actions import StudioRobotActions
from momo.application.studio_commands import MotionDraftGotoCommand
from momo.domain.enums import MotionCommandSource, MotionCommandState, RobotVariant
from momo.domain.errors import (
    CaptureStateChangedError,
    EntityNotFoundError,
    RevisionConflictError,
)
from momo.domain.motion import MotionKeyframe
from momo.domain.motion_command import MotionCommand
from momo.domain.motion_draft import MotionDraft
from momo.domain.motion_preflight import MotionAccepted
from tests.factories import make_snapshot
from tests.stage6_helpers import make_stage6_app


def direct_actions(app: FastAPI) -> StudioRobotActions:
    state = app.state
    studio = state.studio_service
    return StudioRobotActions(
        state.robot_service,
        state.kinematics_service,
        state.motion_service,
        studio.clock,
    )


def test_robot_actions_direct_capture_and_goto_remain_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        actions = direct_actions(app)
        assert "_mutation_lock" not in vars(actions)
        assert "_compile_lock" not in vars(actions)
        await app.state.robot_service.connect()
        submitted: list[MotionCommand] = []
        motion = cast(MotionApplicationService, app.state.motion_service)
        original_submit = motion.submit

        async def observe_submit(command: MotionCommand) -> MotionAccepted:
            submitted.append(command)
            return await original_submit(command)

        monkeypatch.setattr(motion, "submit", observe_submit)

        snapshot = await actions.capture_snapshot()
        keyframe = MotionKeyframe(label="Captured", pose_snapshot=snapshot)
        draft = MotionDraft(
            name="Direct robot action",
            robot_variant=RobotVariant.V2,
            keyframes=[keyframe],
        )
        accepted = await actions.goto_keyframe(
            draft,
            keyframe.id,
            MotionDraftGotoCommand(
                expected_revision=draft.revision,
                duration_s=0.1,
                speed_scale=0.5,
                idempotency_key="direct-studio-goto",
            ),
        )

        assert accepted.status is MotionCommandState.ACCEPTED
        status = motion.get_status(accepted.command_id)
        assert status.preflight.accepted is True
        checks = {item.name: item for item in status.preflight.checks}
        assert checks["command_source"].passed is True
        assert [command.source for command in submitted] == [MotionCommandSource.STUDIO]
        assert status.hardware_accessed is False
        await motion.stop()

    asyncio.run(scenario())


def test_robot_actions_direct_preserve_revision_and_keyframe_guards(tmp_path: Path) -> None:
    async def scenario() -> None:
        actions = direct_actions(make_stage6_app(tmp_path))
        keyframe = MotionKeyframe(label="Persisted", pose_snapshot=make_snapshot())
        draft = MotionDraft(
            name="Guarded action",
            robot_variant=RobotVariant.V2,
            keyframes=[keyframe],
        )
        stale_request = MotionDraftGotoCommand(
            expected_revision=2,
            idempotency_key="stale-direct-goto",
        )
        with pytest.raises(RevisionConflictError) as stale:
            await actions.goto_keyframe(draft, keyframe.id, stale_request)
        assert stale.value.details == {
            "entity": "MotionDraft",
            "expected_revision": 2,
            "actual_revision": 1,
        }

        missing_request = MotionDraftGotoCommand(
            expected_revision=1,
            idempotency_key="missing-direct-goto",
        )
        with pytest.raises(EntityNotFoundError):
            await actions.goto_keyframe(draft, uuid4(), missing_request)

    asyncio.run(scenario())


def test_robot_actions_direct_capture_fails_closed_when_disconnected(tmp_path: Path) -> None:
    async def scenario() -> None:
        actions = direct_actions(make_stage6_app(tmp_path))
        with pytest.raises(CaptureStateChangedError) as raised:
            await actions.capture_snapshot()
        assert raised.value.details == {"reason": "ROBOT_NOT_READY"}

    asyncio.run(scenario())
