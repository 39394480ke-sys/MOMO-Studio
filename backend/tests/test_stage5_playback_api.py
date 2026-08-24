"""Stage 5 trajectory/playback API integration and shared-gateway safety tests."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.enums import (
    Easing,
    MotionCommandSource,
    MotionCommandState,
    MotionCommandType,
    MotionMode,
)
from momo.domain.errors import (
    MotionConflictError,
    MotionPreflightError,
    PreparedTrajectoryNotFoundError,
)
from momo.domain.motion import Motion, MotionKeyframe, MotionTransition
from momo.domain.motion_command import JointMovePayload, MotionCommand
from momo.domain.playback import PlaybackState
from momo.domain.pose import PoseSnapshot, SnapshotJointState
from momo.domain.robot import JointState
from tests.stage4_helpers import api_request, make_stage4_app


async def _store_joint_motion(
    app: FastAPI,
    *,
    duration_s: float = 0.05,
    delta: float = 0.001,
    closed_loop: bool = False,
) -> Motion:
    robot: RobotApplicationService = app.state.robot_service
    kinematics: KinematicsService = app.state.kinematics_service
    status, profile, start = await robot.get_motion_snapshot()
    model = kinematics.model_for(profile)

    async def snapshot(state: JointState) -> PoseSnapshot:
        forward = await kinematics.forward(
            profile,
            state,
            state_sequence=status.state_sequence,
            robot_id=status.robot_id,
        )
        return PoseSnapshot(
            robot_variant=profile.variant,
            joint_state=SnapshotJointState.model_validate(
                state.model_dump(mode="python", round_trip=True)
            ),
            tcp_pose=forward.tcp_pose,
            profile_fingerprint=profile.fingerprint,
            kinematics_fingerprint=model.fingerprint,
            state_sequence=status.state_sequence,
        )

    positions = dict(start.positions)
    positions[profile.enabled_joints[0]] += delta
    end = JointState(positions=positions, units=dict(start.units or {})).validate_against(profile)
    keyframes = [
        MotionKeyframe(label="Start", pose_snapshot=await snapshot(start)),
        MotionKeyframe(
            label="End",
            pose_snapshot=await snapshot(start if closed_loop else end),
            incoming_transition=MotionTransition(
                duration_s=duration_s,
                motion_mode=MotionMode.JOINT,
                easing=Easing.LINEAR,
            ),
        ),
    ]
    motion = Motion(
        name="Stage 5 API fixture",
        robot_variant=profile.variant,
        keyframes=keyframes,
    )
    await app.state.library_service.motions.save(motion)
    return motion


async def _ordinary_joint_command(app: FastAPI, *, idempotency_key: str) -> MotionCommand:
    robot: RobotApplicationService = app.state.robot_service
    status, profile, current = await robot.get_motion_snapshot()
    positions = dict(current.positions)
    positions[profile.enabled_joints[0]] += 0.01
    return MotionCommand(
        robot_id=status.robot_id,
        source=MotionCommandSource.CONTROL,
        expected_state_sequence=status.state_sequence,
        expected_profile_fingerprint=profile.fingerprint,
        expected_kinematics_fingerprint=app.state.kinematics_service.model_for(profile).fingerprint,
        command_type=MotionCommandType.MOVE_JOINTS,
        payload=JointMovePayload(
            joint_state=JointState(positions=positions, units=current.units),
            duration_s=1.0,
        ),
        idempotency_key=idempotency_key,
    )


async def _wait_for_state(
    app: FastAPI,
    expected: set[PlaybackState],
    *,
    attempts: int = 200,
) -> PlaybackState:
    for _ in range(attempts):
        state = cast(PlaybackState, app.state.playback_service.get_status().state)
        if state in expected:
            return state
        await asyncio.sleep(0.005)
    raise AssertionError(
        f"playback did not reach {sorted(item.value for item in expected)}; "
        f"last={app.state.playback_service.get_status().state.value}"
    )


def test_preflight_preview_and_play_execute_the_same_digest(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await app.state.robot_service.connect()
        motion = await _store_joint_motion(app)

        preflight = await api_request(
            app,
            "POST",
            f"/api/v1/motions/{motion.id}/preflight",
            json_data={"expected_revision": 1, "sample_rate_hz": 20.0},
        )
        assert preflight.status_code == 200, preflight.text
        report = preflight.json()
        assert report["passed"] is True
        assert report["digest"]
        assert report["sample_count"] == 2
        assert report["real_motion_ready"] is False
        assert report["field_acceptance_ready"] is False
        assert report["hardware_accessed"] is False

        preview = await api_request(
            app,
            "GET",
            f"/api/v1/trajectory/{report['digest']}/preview",
        )
        assert preview.status_code == 200, preview.text
        preview_payload = preview.json()
        assert preview_payload["digest"] == report["digest"]
        assert preview_payload["motion_id"] == str(motion.id)
        assert preview_payload["sample_count"] == report["sample_count"]
        assert preview_payload["segments"][0]["motion_mode"] == "JOINT"
        assert len(preview_payload["keyframe_markers"]) == 2
        assert preview_payload["joint_series"]
        assert preview_payload["tcp_path"]

        play = await api_request(
            app,
            "POST",
            f"/api/v1/motions/{motion.id}/play",
            json_data={
                "expected_revision": 1,
                "trajectory_digest": report["digest"],
                "loop": False,
                "rate": 2.0,
            },
        )
        assert play.status_code == 202, play.text
        assert play.json()["trajectory_digest"] == report["digest"]
        assert await _wait_for_state(app, {PlaybackState.COMPLETED}) is PlaybackState.COMPLETED
        final = app.state.playback_service.get_status()
        assert final.progress == 1.0
        assert final.current_sample_index == 1
        assert final.hardware_accessed is False
        await app.state.motion_service.shutdown()

    asyncio.run(scenario())


def test_rejected_preflight_stale_revision_and_unknown_preview_are_structured(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        motion = await _store_joint_motion(app)
        rejected = await api_request(
            app,
            "POST",
            f"/api/v1/motions/{motion.id}/preflight",
            json_data={"expected_revision": 1},
        )
        assert rejected.status_code == 200, rejected.text
        payload = rejected.json()
        assert payload["passed"] is False
        assert payload["digest"] is None
        assert "ROBOT_NOT_CONNECTED" in {violation["code"] for violation in payload["violations"]}
        assert app.state.playback_service.get_status().state is PlaybackState.FAULTED

        unknown = await api_request(
            app,
            "GET",
            f"/api/v1/trajectory/{'f' * 64}/preview",
        )
        assert unknown.status_code == 404
        assert unknown.json()["code"] == "PREPARED_TRAJECTORY_NOT_FOUND"

        await app.state.robot_service.connect()
        accepted = await api_request(
            app,
            "POST",
            f"/api/v1/motions/{motion.id}/preflight",
            json_data={"expected_revision": 1},
        )
        assert accepted.json()["passed"] is True
        updated = motion.model_copy(update={"revision": 2})
        await app.state.library_service.motions.save(updated, expected_revision=1)
        stale = await api_request(
            app,
            "POST",
            f"/api/v1/motions/{motion.id}/play",
            json_data={
                "expected_revision": 1,
                "trajectory_digest": accepted.json()["digest"],
                "loop": False,
                "rate": 1.0,
            },
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "REVISION_CONFLICT"
        await app.state.motion_service.shutdown()

    asyncio.run(scenario())


def test_pause_rate_resume_stop_and_shared_motion_slot(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        await robot.connect()
        motion = await _store_joint_motion(app, duration_s=0.5, delta=0.1)
        preflight = await api_request(
            app,
            "POST",
            f"/api/v1/motions/{motion.id}/preflight",
            json_data={"expected_revision": 1},
        )
        digest = preflight.json()["digest"]
        play = await api_request(
            app,
            "POST",
            f"/api/v1/motions/{motion.id}/play",
            json_data={
                "expected_revision": 1,
                "trajectory_digest": digest,
                "loop": False,
                "rate": 1.0,
            },
        )
        assert play.status_code == 202
        await _wait_for_state(app, {PlaybackState.PLAYING})

        status, profile, current = await robot.get_motion_snapshot()
        positions = dict(current.positions)
        positions[profile.enabled_joints[0]] += 0.01
        ordinary = MotionCommand(
            robot_id=status.robot_id,
            source=MotionCommandSource.CONTROL,
            expected_state_sequence=status.state_sequence,
            expected_profile_fingerprint=profile.fingerprint,
            expected_kinematics_fingerprint=app.state.kinematics_service.model_for(
                profile
            ).fingerprint,
            command_type=MotionCommandType.MOVE_JOINTS,
            payload=JointMovePayload(
                joint_state=JointState(positions=positions, units=current.units),
                duration_s=1.0,
            ),
            idempotency_key="ordinary-during-playback",
        )
        with pytest.raises(MotionPreflightError) as conflict:
            await app.state.motion_service.submit(ordinary)
        assert conflict.value.details is not None

        paused = await api_request(app, "POST", "/api/v1/playback/pause")
        assert paused.status_code == 200, paused.text
        assert paused.json()["state"] == "PAUSED"
        before = (await robot.get_status()).positions
        await asyncio.sleep(0.03)
        assert (await robot.get_status()).positions == before

        rate = await api_request(
            app,
            "PUT",
            "/api/v1/playback/rate",
            json_data={"rate": 1.5},
        )
        assert rate.status_code == 200
        assert rate.json()["rate"] == 1.5
        discontinuous_loop = await api_request(
            app,
            "PUT",
            "/api/v1/playback/loop",
            json_data={"loop": True},
        )
        assert discontinuous_loop.status_code == 422
        assert discontinuous_loop.json()["code"] == "MOTION_PREFLIGHT_REJECTED"

        resumed = await api_request(app, "POST", "/api/v1/playback/resume")
        assert resumed.status_code == 200
        stopped = await api_request(app, "POST", "/api/v1/playback/stop")
        assert stopped.status_code == 200
        assert stopped.json()["state"] == "STOPPED"
        assert app.state.playback_service.motion_active is False
        await app.state.motion_service.shutdown()

    asyncio.run(scenario())


def test_lifecycle_stop_cancels_compilation_and_cannot_publish_late_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await app.state.robot_service.connect()
        motion = await _store_joint_motion(app, duration_s=0.5, delta=0.1)
        compiler = app.state.trajectory_service.compiler
        original_compile = compiler.compile
        started = asyncio.Event()

        async def blocked_compile(**kwargs: Any) -> Any:
            started.set()
            cancellation_requested = kwargs["cancellation_requested"]
            while not cancellation_requested():
                await asyncio.sleep(0)
            return await original_compile(**kwargs)

        monkeypatch.setattr(compiler, "compile", blocked_compile)
        task = asyncio.create_task(
            app.state.trajectory_service.preflight(
                motion.id,
                expected_revision=1,
                sample_rate_hz=20.0,
            )
        )
        await started.wait()
        await app.state.motion_service.stop()
        with pytest.raises(MotionConflictError):
            await task
        playback = app.state.playback_service
        assert playback.get_status().state is PlaybackState.STOPPED
        assert playback.motion_active is False
        await asyncio.sleep(0)
        assert playback.get_status().state is PlaybackState.STOPPED
        await app.state.motion_service.shutdown()

    asyncio.run(scenario())


def test_concurrent_preflight_cancels_stale_owner_and_serializes_compilers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await app.state.robot_service.connect()
        motion = await _store_joint_motion(app, duration_s=0.5, delta=0.1)
        trajectory = app.state.trajectory_service
        original_compile = trajectory.compiler.compile
        first_started = asyncio.Event()
        calls = 0
        active = 0
        maximum_active = 0

        async def controlled_compile(**kwargs: Any) -> Any:
            nonlocal calls, active, maximum_active
            calls += 1
            call_number = calls
            active += 1
            maximum_active = max(maximum_active, active)
            try:
                if call_number == 1:
                    first_started.set()
                    cancellation_requested = kwargs["cancellation_requested"]
                    while not cancellation_requested():
                        await asyncio.sleep(0)
                    # Simulate a late successful result from a compiler that has
                    # already crossed its last internal cancellation checkpoint.
                    kwargs = {**kwargs, "cancellation_requested": lambda: False}
                return await original_compile(**kwargs)
            finally:
                active -= 1

        monkeypatch.setattr(trajectory.compiler, "compile", controlled_compile)
        stale = asyncio.create_task(
            trajectory.preflight(
                motion.id,
                expected_revision=1,
                sample_rate_hz=20.0,
            )
        )
        await first_started.wait()
        latest = asyncio.create_task(
            trajectory.preflight(
                motion.id,
                expected_revision=1,
                sample_rate_hz=25.0,
            )
        )

        with pytest.raises(MotionConflictError) as superseded:
            await stale
        accepted = await latest

        assert superseded.value.details == {"reason": "TRAJECTORY_COMPILATION_CANCELLED"}
        assert accepted.prepared is not None
        assert accepted.prepared.plan.sample_rate_hz == 25.0
        assert maximum_active == 1
        assert tuple(trajectory._prepared) == (accepted.prepared.plan.digest.sha256,)
        status = app.state.playback_service.get_status()
        assert status.state is PlaybackState.READY
        assert status.trajectory_digest == accepted.prepared.plan.digest.sha256
        await app.state.motion_service.shutdown()

    asyncio.run(scenario())


def test_preview_cache_access_stays_on_the_application_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await app.state.robot_service.connect()
        motion = await _store_joint_motion(app)
        preflight = await api_request(
            app,
            "POST",
            f"/api/v1/motions/{motion.id}/preflight",
            json_data={"expected_revision": 1},
        )
        digest = preflight.json()["digest"]
        trajectory = app.state.trajectory_service
        original_preview = trajectory.preview
        application_thread = threading.get_ident()
        observed_threads: list[int] = []

        def checked_preview(requested_digest: str) -> Any:
            observed_threads.append(threading.get_ident())
            assert threading.get_ident() == application_thread
            return original_preview(requested_digest)

        monkeypatch.setattr(trajectory, "preview", checked_preview)
        response = await api_request(
            app,
            "GET",
            f"/api/v1/trajectory/{digest}/preview",
        )

        assert response.status_code == 200, response.text
        assert observed_threads == [application_thread]
        await app.state.motion_service.shutdown()

    asyncio.run(scenario())


def test_shared_admission_ordinary_final_check_wins_without_dual_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await app.state.robot_service.connect()
        motion = await _store_joint_motion(app, duration_s=0.5, delta=0.1)
        outcome = await app.state.trajectory_service.preflight(
            motion.id,
            expected_revision=1,
            sample_rate_hz=20.0,
        )
        assert outcome.prepared is not None
        digest = outcome.prepared.plan.digest.sha256
        command = await _ordinary_joint_command(
            app,
            idempotency_key="stage5-admission-ordinary-first",
        )
        executor = app.state.motion_service.executor
        playback = app.state.playback_service
        original_submit = executor.submit
        ordinary_at_submit = asyncio.Event()
        release_ordinary = asyncio.Event()
        play_loaded_motion = asyncio.Event()
        overlaps: list[bool] = []

        async def blocked_submit(prepared: Any) -> Any:
            ordinary_at_submit.set()
            await release_ordinary.wait()
            status = await original_submit(prepared)
            overlaps.append(executor.active_command_id is not None and playback.motion_active)
            return status

        original_get_motion = app.state.library_service.get_motion

        async def observed_get_motion(motion_id: Any) -> Any:
            value = await original_get_motion(motion_id)
            play_loaded_motion.set()
            return value

        monkeypatch.setattr(executor, "submit", blocked_submit)
        ordinary = asyncio.create_task(app.state.motion_service.submit(command))
        await ordinary_at_submit.wait()
        monkeypatch.setattr(app.state.library_service, "get_motion", observed_get_motion)
        play = asyncio.create_task(
            app.state.trajectory_service.play(
                motion.id,
                expected_revision=1,
                trajectory_digest=digest,
                loop=False,
                rate=1.0,
            )
        )
        await play_loaded_motion.wait()

        assert playback.motion_active is False
        assert executor.active_command_id is None
        release_ordinary.set()
        await ordinary
        with pytest.raises(MotionConflictError) as conflict:
            await play

        assert conflict.value.details == {"reason": "MOTION_SLOT_OCCUPIED"}
        assert executor.active_command_id is not None
        assert playback.motion_active is False
        assert overlaps == [False]
        await app.state.motion_service.stop()
        await app.state.motion_service.shutdown()

    asyncio.run(scenario())


def test_shared_admission_blocks_preflight_claim_during_ordinary_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await app.state.robot_service.connect()
        motion = await _store_joint_motion(app, duration_s=0.5, delta=0.1)
        command = await _ordinary_joint_command(
            app,
            idempotency_key="stage5-admission-preflight-race",
        )
        executor = app.state.motion_service.executor
        playback = app.state.playback_service
        original_submit = executor.submit
        ordinary_at_submit = asyncio.Event()
        release_ordinary = asyncio.Event()
        preflight_loaded_motion = asyncio.Event()
        overlaps: list[bool] = []

        async def blocked_submit(prepared: Any) -> Any:
            ordinary_at_submit.set()
            await release_ordinary.wait()
            status = await original_submit(prepared)
            overlaps.append(executor.active_command_id is not None and playback.motion_active)
            return status

        original_get_motion = app.state.library_service.get_motion

        async def observed_get_motion(motion_id: Any) -> Any:
            value = await original_get_motion(motion_id)
            preflight_loaded_motion.set()
            return value

        monkeypatch.setattr(executor, "submit", blocked_submit)
        ordinary = asyncio.create_task(app.state.motion_service.submit(command))
        await ordinary_at_submit.wait()
        monkeypatch.setattr(app.state.library_service, "get_motion", observed_get_motion)
        preflight = asyncio.create_task(
            app.state.trajectory_service.preflight(
                motion.id,
                expected_revision=1,
                sample_rate_hz=20.0,
            )
        )
        await preflight_loaded_motion.wait()

        assert playback.motion_active is False
        assert executor.active_command_id is None
        release_ordinary.set()
        await ordinary
        with pytest.raises(MotionConflictError) as conflict:
            await preflight

        assert conflict.value.details == {"reason": "MOTION_SLOT_OCCUPIED"}
        assert executor.active_command_id is not None
        assert playback.motion_active is False
        assert overlaps == [False]
        await app.state.motion_service.stop()
        await app.state.motion_service.shutdown()

    asyncio.run(scenario())


def test_shared_admission_playback_final_check_wins_without_dual_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await app.state.robot_service.connect()
        motion = await _store_joint_motion(app, duration_s=0.5, delta=0.1)
        outcome = await app.state.trajectory_service.preflight(
            motion.id,
            expected_revision=1,
            sample_rate_hz=20.0,
        )
        assert outcome.prepared is not None
        digest = outcome.prepared.plan.digest.sha256
        command = await _ordinary_joint_command(
            app,
            idempotency_key="stage5-admission-playback-first",
        )
        trajectory = app.state.trajectory_service
        playback = app.state.playback_service
        executor = app.state.motion_service.executor
        original_play = playback.play
        playback_at_claim = asyncio.Event()
        release_playback = asyncio.Event()
        ordinary_prepared = asyncio.Event()
        overlaps: list[bool] = []

        async def blocked_play(*args: Any, **kwargs: Any) -> Any:
            playback_at_claim.set()
            await release_playback.wait()
            status = await original_play(*args, **kwargs)
            overlaps.append(executor.active_command_id is not None and playback.motion_active)
            return status

        original_prepare = app.state.motion_service.gateway.prepare

        async def observed_prepare(command_value: Any) -> Any:
            value = await original_prepare(command_value)
            ordinary_prepared.set()
            return value

        monkeypatch.setattr(playback, "play", blocked_play)
        play = asyncio.create_task(
            trajectory.play(
                motion.id,
                expected_revision=1,
                trajectory_digest=digest,
                loop=False,
                rate=1.0,
            )
        )
        await playback_at_claim.wait()
        monkeypatch.setattr(app.state.motion_service.gateway, "prepare", observed_prepare)
        ordinary = asyncio.create_task(app.state.motion_service.submit(command))
        await ordinary_prepared.wait()

        assert executor.active_command_id is None
        assert playback.motion_active is False
        release_playback.set()
        await play
        with pytest.raises(MotionConflictError):
            await ordinary

        assert playback.motion_active is True
        assert executor.active_command_id is None
        assert overlaps == [False]
        await app.state.motion_service.stop()
        await app.state.motion_service.shutdown()

    asyncio.run(scenario())


def test_play_rejects_evicted_prepared_identity_after_repository_await(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await app.state.robot_service.connect()
        motion = await _store_joint_motion(app, duration_s=0.5, delta=0.1)
        trajectory = app.state.trajectory_service
        initial = await trajectory.preflight(
            motion.id,
            expected_revision=1,
            sample_rate_hz=20.0,
        )
        assert initial.prepared is not None
        digest = initial.prepared.plan.digest.sha256
        play_waiting = asyncio.Event()
        release_play = asyncio.Event()
        play_task: asyncio.Task[Any] | None = None
        original_get_motion = app.state.library_service.get_motion

        async def controlled_get_motion(motion_id: Any) -> Any:
            value = await original_get_motion(motion_id)
            if asyncio.current_task() is play_task:
                play_waiting.set()
                await release_play.wait()
            return value

        monkeypatch.setattr(app.state.library_service, "get_motion", controlled_get_motion)
        play_task = asyncio.create_task(
            trajectory.play(
                motion.id,
                expected_revision=1,
                trajectory_digest=digest,
                loop=False,
                rate=1.0,
            )
        )
        await play_waiting.wait()
        original_compile = trajectory.compiler.compile

        async def rejected_compile(**kwargs: Any) -> Any:
            return await original_compile(**{**kwargs, "connected": False})

        monkeypatch.setattr(trajectory.compiler, "compile", rejected_compile)
        rejected = await trajectory.preflight(
            motion.id,
            expected_revision=1,
            sample_rate_hz=25.0,
        )
        assert rejected.prepared is None
        assert digest not in trajectory._prepared

        release_play.set()
        with pytest.raises(PreparedTrajectoryNotFoundError):
            await play_task

        assert app.state.playback_service.get_status().state is PlaybackState.FAULTED
        assert app.state.playback_service.motion_active is False
        await app.state.motion_service.shutdown()

    asyncio.run(scenario())


def test_lifecycle_stop_fences_requests_started_after_trajectory_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await app.state.robot_service.connect()
        motion = await _store_joint_motion(app, duration_s=0.5, delta=0.1)
        trajectory = app.state.trajectory_service
        initial = await trajectory.preflight(
            motion.id,
            expected_revision=1,
            sample_rate_hz=20.0,
        )
        assert initial.prepared is not None
        digest = initial.prepared.plan.digest.sha256
        robot_stop_entered = asyncio.Event()
        release_robot_stop = asyncio.Event()
        original_stop = app.state.robot_service.stop

        async def blocked_robot_stop() -> Any:
            robot_stop_entered.set()
            await release_robot_stop.wait()
            return await original_stop()

        monkeypatch.setattr(app.state.robot_service, "stop", blocked_robot_stop)
        stop_task = asyncio.create_task(app.state.motion_service.stop())
        await robot_stop_entered.wait()

        with pytest.raises(MotionConflictError) as preflight_conflict:
            await trajectory.preflight(
                motion.id,
                expected_revision=1,
                sample_rate_hz=25.0,
            )
        with pytest.raises(MotionConflictError) as play_conflict:
            await trajectory.play(
                motion.id,
                expected_revision=1,
                trajectory_digest=digest,
                loop=False,
                rate=1.0,
            )

        assert preflight_conflict.value.details == {"reason": "LIFECYCLE_EPOCH_CHANGED"}
        assert play_conflict.value.details == {"reason": "LIFECYCLE_EPOCH_CHANGED"}
        assert app.state.playback_service.get_status().state is PlaybackState.STOPPED
        release_robot_stop.set()
        response = await stop_task
        assert response.result == "STOPPED"
        assert app.state.playback_service.get_status().state is PlaybackState.STOPPED
        await app.state.motion_service.shutdown()

    asyncio.run(scenario())


def test_lifecycle_stop_during_preflight_claim_finishes_stopped_not_faulted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await app.state.robot_service.connect()
        motion = await _store_joint_motion(app, duration_s=0.5, delta=0.1)
        trajectory = app.state.trajectory_service
        playback = app.state.playback_service
        claim_published = asyncio.Event()
        release_claim = asyncio.Event()
        original_begin_preflight = playback.begin_preflight

        async def blocked_begin_preflight(motion_id: UUID, revision: int) -> Any:
            status = await original_begin_preflight(motion_id, revision)
            claim_published.set()
            await release_claim.wait()
            return status

        monkeypatch.setattr(playback, "begin_preflight", blocked_begin_preflight)
        preflight_task = asyncio.create_task(
            trajectory.preflight(
                motion.id,
                expected_revision=1,
                sample_rate_hz=20.0,
            )
        )
        await claim_published.wait()
        assert playback.get_status().state is PlaybackState.PREFLIGHTING

        stop_task = asyncio.create_task(app.state.motion_service.stop())
        for _ in range(100):
            if app.state.motion_service.gateway.motion_admission.lifecycle_count == 1:
                break
            await asyncio.sleep(0)
        else:
            raise AssertionError("lifecycle Stop did not establish its epoch fence")
        release_claim.set()

        with pytest.raises(MotionConflictError) as conflict:
            await preflight_task
        response = await stop_task
        assert conflict.value.details == {"reason": "LIFECYCLE_EPOCH_CHANGED"}
        assert response.result == "STOPPED"
        assert playback.get_status().state is PlaybackState.STOPPED
        assert playback.get_status().error != "Trajectory preflight failed"
        assert playback.motion_active is False
        await app.state.motion_service.shutdown()

    asyncio.run(scenario())


def test_lifecycle_stop_rolls_back_ordinary_claim_after_submit_await(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await app.state.robot_service.connect()
        motion_service = app.state.motion_service
        executor = motion_service.executor
        command = await _ordinary_joint_command(
            app,
            idempotency_key="stage5-post-submit-lifecycle-fence",
        )
        submit_entered = asyncio.Event()
        release_submit = asyncio.Event()
        original_submit = executor.submit

        async def blocked_submit(prepared: Any) -> Any:
            submit_entered.set()
            await release_submit.wait()
            return await original_submit(prepared)

        monkeypatch.setattr(executor, "submit", blocked_submit)
        submit_task = asyncio.create_task(motion_service.submit(command))
        await submit_entered.wait()
        stop_task = asyncio.create_task(motion_service.stop())
        for _ in range(100):
            if motion_service.gateway.motion_admission.lifecycle_count == 1:
                break
            await asyncio.sleep(0)
        else:
            raise AssertionError("lifecycle Stop did not establish its epoch fence")
        release_submit.set()

        with pytest.raises(MotionConflictError) as conflict:
            await submit_task
        stopped = await stop_task
        status = executor.get_status(command.command_id)
        assert conflict.value.details == {"reason": "LIFECYCLE_EPOCH_CHANGED"}
        assert stopped.result == "STOPPED"
        assert status is not None
        assert status.state is MotionCommandState.CANCELLED
        assert executor.active_command_id is None
        await motion_service.shutdown()

    asyncio.run(scenario())


def test_cancelled_global_stop_caller_cannot_skip_trajectory_hook(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await app.state.robot_service.connect()
        motion = await _store_joint_motion(app)
        motion_service = app.state.motion_service
        playback = app.state.playback_service
        await playback.begin_preflight(motion.id, motion.revision)
        first_hook_entered = asyncio.Event()
        release_first_hook = asyncio.Event()
        original_first_hook = motion_service._stop_hooks[0]

        async def blocked_first_hook() -> None:
            first_hook_entered.set()
            await release_first_hook.wait()
            await original_first_hook()

        motion_service._stop_hooks[0] = blocked_first_hook
        first_stop = asyncio.create_task(motion_service.stop())
        await first_hook_entered.wait()
        first_stop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first_stop

        assert motion_service.gateway.motion_admission.lifecycle_count == 1
        assert playback.get_status().state is PlaybackState.PREFLIGHTING
        assert playback.motion_active is True
        second_stop = asyncio.create_task(motion_service.stop())
        await asyncio.sleep(0)
        assert second_stop.done() is False

        release_first_hook.set()
        stopped = await second_stop
        assert stopped.result == "STOPPED"
        assert motion_service.gateway.motion_admission.lifecycle_count == 0
        assert playback.get_status().state is PlaybackState.STOPPED
        assert playback.motion_active is False
        assert motion_service._stop_completion_task is None
        await motion_service.shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize("mutation", ["update", "delete"])
def test_motion_mutation_linearizes_after_validated_playing_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await app.state.robot_service.connect()
        motion = await _store_joint_motion(app, duration_s=0.5, delta=0.1)
        trajectory = app.state.trajectory_service
        playback = app.state.playback_service
        outcome = await trajectory.preflight(
            motion.id,
            expected_revision=1,
            sample_rate_hz=20.0,
        )
        assert outcome.prepared is not None
        digest = outcome.prepared.plan.digest.sha256
        validation_entered = asyncio.Event()
        release_validation = asyncio.Event()
        gateway = app.state.motion_service.gateway
        original_validate = gateway.validate_prepared_trajectory

        async def blocked_validate(*args: Any, **kwargs: Any) -> Any:
            validation_entered.set()
            await release_validation.wait()
            return await original_validate(*args, **kwargs)

        monkeypatch.setattr(gateway, "validate_prepared_trajectory", blocked_validate)
        commit_states: list[PlaybackState] = []
        repository = app.state.library_service.motions
        if mutation == "update":
            original_save = repository.save

            async def observed_save(
                value: Motion,
                *,
                expected_revision: int | None = None,
            ) -> None:
                commit_states.append(playback.get_status().state)
                await original_save(value, expected_revision=expected_revision)

            monkeypatch.setattr(repository, "save", observed_save)
        else:
            original_delete = repository.delete

            async def observed_delete(
                motion_id: UUID,
                *,
                expected_revision: int,
            ) -> bool:
                commit_states.append(playback.get_status().state)
                return cast(
                    bool,
                    await original_delete(
                        motion_id,
                        expected_revision=expected_revision,
                    ),
                )

            monkeypatch.setattr(repository, "delete", observed_delete)

        await trajectory.play(
            motion.id,
            expected_revision=1,
            trajectory_digest=digest,
            loop=False,
            rate=0.25,
        )
        await validation_entered.wait()
        if mutation == "update":
            mutation_task = asyncio.create_task(
                api_request(
                    app,
                    "PATCH",
                    f"/api/v1/motions/{motion.id}",
                    json_data={"expected_revision": 1, "name": "Changed after claim"},
                )
            )
        else:
            mutation_task = asyncio.create_task(
                api_request(
                    app,
                    "DELETE",
                    f"/api/v1/motions/{motion.id}?expected_revision=1",
                )
            )
        for _ in range(10):
            await asyncio.sleep(0)
        assert mutation_task.done() is False
        assert commit_states == []

        release_validation.set()
        response = await mutation_task
        assert response.status_code == (200 if mutation == "update" else 204), response.text
        assert commit_states == [PlaybackState.PLAYING]
        assert playback.get_status().state is PlaybackState.PLAYING
        await trajectory.stop()
        await app.state.motion_service.shutdown()

    asyncio.run(scenario())


def test_robot_websocket_includes_typed_read_only_playback_status(tmp_path: Path) -> None:
    app = make_stage4_app(tmp_path)
    asyncio.run(app.state.robot_service.connect())
    with (
        TestClient(app) as client,
        client.websocket_connect(
            "/api/v1/ws/robot",
            headers={"origin": "http://127.0.0.1:8000"},
        ) as socket,
    ):
        payload = socket.receive_json()
        assert payload["playback_status"]["state"] == "IDLE"
        assert payload["playback_status"]["hardware_accessed"] is False
        assert payload["hardware_accessed"] is False


def test_runtime_fault_is_sanitized_in_http_and_websocket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_stage4_app(tmp_path)
    sensitive = (
        "Traceback (most recent call last): /Users/operator/private.py token=stage5-super-secret"
    )
    public_reason = "Playback execution failed (PLAYBACK_RUNTIME_FAULT)"

    async def scenario() -> None:
        await app.state.robot_service.connect()
        motion = await _store_joint_motion(app)
        preflight = await api_request(
            app,
            "POST",
            f"/api/v1/motions/{motion.id}/preflight",
            json_data={"expected_revision": 1},
        )
        assert preflight.status_code == 200

        async def fail_state_application(command_id: object, state: object) -> int:
            del command_id, state
            raise RuntimeError(sensitive)

        monkeypatch.setattr(
            app.state.robot_service,
            "apply_motion_state",
            fail_state_application,
        )
        play = await api_request(
            app,
            "POST",
            f"/api/v1/motions/{motion.id}/play",
            json_data={
                "expected_revision": 1,
                "trajectory_digest": preflight.json()["digest"],
                "loop": False,
                "rate": 1.0,
            },
        )
        assert play.status_code == 202
        assert await _wait_for_state(app, {PlaybackState.FAULTED}) is PlaybackState.FAULTED
        response = await api_request(app, "GET", "/api/v1/playback")
        assert response.status_code == 200
        assert response.json()["error"] == public_reason
        assert sensitive not in response.text

    asyncio.run(scenario())

    with (
        TestClient(app) as client,
        client.websocket_connect(
            "/api/v1/ws/robot",
            headers={"origin": "http://127.0.0.1:8000"},
        ) as socket,
    ):
        payload = socket.receive_json()
        assert payload["playback_status"]["state"] == "FAULTED"
        assert payload["playback_status"]["error"] == public_reason
        rendered = str(payload)
        assert "Traceback" not in rendered
        assert "/Users/operator" not in rendered
        assert "stage5-super-secret" not in rendered
