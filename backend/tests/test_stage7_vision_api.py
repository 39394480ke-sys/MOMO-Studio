"""Stage 7 Vision API and orchestration safety integration tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI

from momo.adapters.vision import SyntheticFrameSource
from momo.api.app import create_app
from momo.application.services.vision_service import VisionApplicationService
from momo.domain.enums import DomainUnit, ProfileVerificationStatus
from momo.domain.errors import (
    VisionFollowConflictError,
    VisionFrameConflictError,
    VisionProviderUnavailableError,
)
from momo.domain.vision import (
    CameraAccessPolicy,
    Detection,
    NormalizedBoundingBox,
    TargetSelection,
    TrackingResult,
    TrackingStatus,
    VisionFrame,
    VisionProviderCapability,
    VisionProviderKind,
    VisionProviderStatus,
    VisionStatus,
)
from momo.domain.vision_follow import (
    FollowActuatorMapping,
    FollowConfiguration,
    FollowOperatorIntent,
    FollowState,
    FollowStopReason,
)
from momo.ports.target_tracker import TargetTracker
from momo.ports.vision_detection import TargetDetector
from momo.settings import Settings


def make_app(tmp_path: Path) -> FastAPI:
    return create_app(
        Settings(
            runtime_state_directory=str(tmp_path / "runtime"),
            calibration_directory=str(tmp_path / "calibration"),
            pose_directory=str(tmp_path / "poses"),
            motion_library_directory=str(tmp_path / "motions"),
            motion_draft_directory=str(tmp_path / "drafts"),
        )
    )


def make_live_app(tmp_path: Path) -> FastAPI:
    return create_app(
        Settings(
            camera_access_policy=CameraAccessPolicy.LIVE_CAMERA_ALLOWED,
            live_camera_device_id="explicit-test-device",
            live_camera_local_config_enabled=True,
            vision_frame_width_px=1280,
            vision_frame_height_px=720,
            vision_max_fps=30.0,
            runtime_state_directory=str(tmp_path / "runtime"),
            calibration_directory=str(tmp_path / "calibration"),
            pose_directory=str(tmp_path / "poses"),
            motion_library_directory=str(tmp_path / "motions"),
            motion_draft_directory=str(tmp_path / "drafts"),
        )
    )


async def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json_data: object | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=json_data)


async def shutdown(app: FastAPI) -> None:
    await app.state.vision_service.shutdown()
    await app.state.motion_service.shutdown()


def follow_request(profile: dict[str, Any]) -> dict[str, object]:
    angular = [
        item["joint_id"]
        for item in profile["joint_definitions"]
        if item["domain_unit"] == DomainUnit.DEG.value
    ]
    assert len(angular) >= 2
    return {
        "configuration": {
            "dead_zone_x": 0.08,
            "dead_zone_y": 0.08,
            "ema_alpha": 0.35,
            "gain": 0.5,
            "max_step": 2.0,
            "max_rate": 4.0,
            "confidence_threshold": 0.55,
            "frame_freshness_limit_s": 0.75,
            "target_lost_limit_s": 0.5,
            "lease_ttl_s": 2.0,
        },
        "mapping": {
            "pan_joint": angular[0],
            "tilt_joint": angular[1],
            "pan_sign": 1,
            "tilt_sign": -1,
            "verification_status": ProfileVerificationStatus.VERIFIED_FOR_DRY_RUN.value,
        },
    }


class _FakeOperatorCameraSource:
    source_id = "live-camera-read-only"

    def __init__(self) -> None:
        self.status = VisionStatus.CLOSED
        self.open_calls = 0
        self.close_calls = 0
        self.sequence = 0
        self.capability = VisionProviderCapability(
            provider_id="opencv-camera-source",
            kind=VisionProviderKind.FRAME_SOURCE,
            status=VisionProviderStatus.AVAILABLE,
            display_name="Fake live camera",
            model_source="Test fixture",
            notice="No real device access",
        )

    async def open(self) -> None:
        self.open_calls += 1
        self.status = VisionStatus.READY

    async def latest_frame(self) -> VisionFrame | None:
        if self.status not in {VisionStatus.READY, VisionStatus.STREAMING}:
            return None
        self.sequence += 1
        self.status = VisionStatus.STREAMING
        return VisionFrame.model_validate(
            {
                "metadata": {
                    "frame_id": f"live-camera-read-only-{self.sequence:08d}",
                    "source_id": self.source_id,
                    "captured_at": datetime.now(UTC),
                    "width_px": 1280,
                    "height_px": 720,
                },
                "content": b"\xff\xd8fake-jpeg\xff\xd9",
                "media_type": "image/jpeg",
            }
        )

    async def aclose(self) -> None:
        self.close_calls += 1
        self.status = VisionStatus.CLOSED


def test_live_camera_requires_explicit_open_and_remains_read_only(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_live_app(tmp_path)
        source = _FakeOperatorCameraSource()
        app.state.vision_service.source = source
        try:
            initial = await request(app, "GET", "/api/v1/vision/status")
            assert initial.status_code == 200
            assert initial.json()["source_state"] == "CLOSED"
            assert initial.json()["latest_frame"] is None

            before_open = await request(app, "GET", "/api/v1/vision/frame")
            assert before_open.status_code == 503
            assert source.open_calls == 0

            unconfirmed = await request(
                app,
                "POST",
                "/api/v1/vision/camera/open",
                json_data={"confirm_read_only_open": False},
            )
            assert unconfirmed.status_code == 422
            assert source.open_calls == 0

            opened = await request(
                app,
                "POST",
                "/api/v1/vision/camera/open",
                json_data={"confirm_read_only_open": True},
            )
            assert opened.status_code == 200, opened.text
            assert opened.json()["source_state"] == "STREAMING"
            assert opened.json()["latest_frame"]["width_px"] == 1280
            assert source.open_calls == 1

            frame = await request(app, "GET", "/api/v1/vision/frame")
            assert frame.status_code == 200
            assert frame.headers["content-type"] == "image/jpeg"
            frame_id = frame.headers["x-frame-id"]
            selected = await request(
                app,
                "POST",
                "/api/v1/vision/selection",
                json_data={
                    "frame_id": frame_id,
                    "bounding_box": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
                },
            )
            assert selected.status_code == 503
            assert "read-only" in selected.json()["message"]

            closed = await request(app, "POST", "/api/v1/vision/camera/close", json_data={})
            assert closed.status_code == 200
            assert closed.json()["source_state"] == "CLOSED"
            assert closed.json()["latest_frame"] is None
            assert source.close_calls == 1
        finally:
            await shutdown(app)

    asyncio.run(scenario())


def test_synthetic_runtime_rejects_live_camera_open(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_app(tmp_path)
        try:
            response = await request(
                app,
                "POST",
                "/api/v1/vision/camera/open",
                json_data={"confirm_read_only_open": True},
            )
            assert response.status_code == 503
            assert app.state.vision_service.source.capability.provider_id == (
                "synthetic-frame-source"
            )
        finally:
            await shutdown(app)

    asyncio.run(scenario())


def test_synthetic_api_detection_selection_follow_and_global_stop(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_app(tmp_path)
        try:
            capabilities = await request(app, "GET", "/api/v1/vision/capabilities")
            assert capabilities.status_code == 200
            capability_data = capabilities.json()
            assert capability_data["camera_access_policy"] == "SYNTHETIC_ONLY"
            assert capability_data["source"]["provider_id"] == "synthetic-frame-source"
            assert capability_data["source"]["available"] is True
            assert capability_data["real_follow_allowed"] is False
            assert any(
                item["provider_id"] == "opencv-live-target-tracker" and item["available"] is False
                for item in capability_data["trackers"]
            )

            frame = await request(app, "GET", "/api/v1/vision/frame")
            assert frame.status_code == 200
            assert frame.headers["content-type"] == "image/png"
            assert frame.content.startswith(b"\x89PNG\r\n\x1a\n")
            assert frame.headers["cache-control"] == "no-store, max-age=0"

            status = (await request(app, "GET", "/api/v1/vision/status")).json()
            frame_id = status["latest_frame"]["frame_id"]
            assert frame_id == frame.headers["x-frame-id"]
            invalid_box = await request(
                app,
                "POST",
                "/api/v1/vision/selection",
                json_data={
                    "frame_id": frame_id,
                    "bounding_box": {
                        "x": 0.9,
                        "y": 0.1,
                        "width": 0.2,
                        "height": 0.2,
                    },
                },
            )
            assert invalid_box.status_code == 422
            unknown_frame = await request(
                app,
                "POST",
                "/api/v1/vision/selection",
                json_data={
                    "frame_id": "synthetic-stage7-99999999",
                    "bounding_box": {
                        "x": 0.1,
                        "y": 0.1,
                        "width": 0.2,
                        "height": 0.2,
                    },
                },
            )
            assert unknown_frame.status_code == 409
            assert unknown_frame.json()["code"] == "VISION_FRAME_CONFLICT"
            detected = await request(
                app,
                "POST",
                "/api/v1/vision/detect/person",
                json_data={"frame_id": frame_id},
            )
            assert detected.status_code == 200
            detection_data = detected.json()
            assert detection_data["capability"]["provider_id"] == ("synthetic-person-detector")
            assert detection_data["detections"][0]["label"] == "person"

            selected = await request(
                app,
                "POST",
                "/api/v1/vision/selection",
                json_data={
                    "frame_id": frame_id,
                    "bounding_box": detection_data["detections"][0]["bounding_box"],
                },
            )
            assert selected.status_code == 200
            assert selected.json()["tracking"]["status"] == "LOCKED"

            assert (await request(app, "POST", "/api/v1/robot/connect")).status_code == 200
            profile = (await request(app, "GET", "/api/v1/robot/profile")).json()["profile"]
            invalid_follow = follow_request(profile)
            invalid_mapping = cast(dict[str, object], invalid_follow["mapping"])
            invalid_mapping["pan_joint"] = "arm_a"
            rejected_mapping = await request(
                app,
                "POST",
                "/api/v1/vision/follow/start",
                json_data=invalid_follow,
            )
            assert rejected_mapping.status_code == 422

            invalid_duration = follow_request(profile)
            invalid_configuration = cast(dict[str, object], invalid_duration["configuration"])
            invalid_configuration["max_step"] = 15.0
            invalid_configuration["max_rate"] = 0.2
            rejected_duration = await request(
                app,
                "POST",
                "/api/v1/vision/follow/start",
                json_data=invalid_duration,
            )
            assert rejected_duration.status_code == 422

            started = await request(
                app,
                "POST",
                "/api/v1/vision/follow/start",
                json_data=follow_request(profile),
            )
            assert started.status_code == 200, started.text
            started_data = started.json()
            assert started_data["status"]["follow"]["active"] is True
            assert started_data["status"]["follow"]["ema_error_x"] is not None
            assert started_data["status"]["dry_run"] is True

            heartbeat = await request(
                app,
                "POST",
                f"/api/v1/vision/follow/{started_data['lease_id']}/heartbeat",
                json_data={},
            )
            assert heartbeat.status_code == 200
            assert heartbeat.json()["lease_id"] == started_data["lease_id"]

            assert (await request(app, "POST", "/api/v1/motion/stop")).status_code == 200
            stopped = (await request(app, "GET", "/api/v1/vision/status")).json()
            assert stopped["follow"]["active"] is False
            assert stopped["follow"]["stop_reason"] == "GLOBAL_STOP"
        finally:
            await shutdown(app)

    asyncio.run(scenario())


class _FaultingTracker:
    def __init__(self, capability: VisionProviderCapability) -> None:
        self.capability = capability

    async def initialize(
        self,
        frame: VisionFrame,
        selection: TargetSelection,
    ) -> TrackingResult:
        del frame, selection
        raise RuntimeError("synthetic tracker initialization fault")

    async def update(self, frame: VisionFrame) -> TrackingResult:
        del frame
        raise RuntimeError("synthetic tracker update fault")

    async def reset(self) -> None:
        return None


class _FaultingDetector:
    def __init__(self, capability: VisionProviderCapability) -> None:
        self.capability = capability

    async def detect(self, frame: VisionFrame) -> tuple[Detection, ...]:
        del frame
        raise RuntimeError("synthetic detector fault")


class _CrossFrameTracker:
    def __init__(self, capability: VisionProviderCapability) -> None:
        self.capability = capability

    async def initialize(
        self,
        frame: VisionFrame,
        selection: TargetSelection,
    ) -> TrackingResult:
        del selection
        return self._foreign_result(frame)

    async def update(self, frame: VisionFrame) -> TrackingResult:
        return self._foreign_result(frame)

    async def reset(self) -> None:
        return None

    @staticmethod
    def _foreign_result(frame: VisionFrame) -> TrackingResult:
        metadata = frame.metadata.model_copy(update={"frame_id": f"{frame.frame_id}-foreign"})
        return TrackingResult(
            metadata=metadata,
            status=TrackingStatus.LOCKED,
            bounding_box=NormalizedBoundingBox.from_metadata(
                x=0.1,
                y=0.1,
                width=0.2,
                height=0.2,
                metadata=metadata,
            ),
            confidence=0.9,
        )


class _FaultingSource:
    def __init__(self, capability: VisionProviderCapability, source_id: str) -> None:
        self.capability = capability
        self.source_id = source_id
        self.status = VisionStatus.READY

    async def latest_frame(self) -> VisionFrame | None:
        raise RuntimeError("synthetic source fault")

    async def aclose(self) -> None:
        self.status = VisionStatus.CLOSED


class _SlowTracker:
    def __init__(self, inner: TargetTracker, delay_s: float) -> None:
        self.inner = inner
        self.delay_s = delay_s
        self.capability = inner.capability

    async def initialize(
        self,
        frame: VisionFrame,
        selection: TargetSelection,
    ) -> TrackingResult:
        await asyncio.sleep(self.delay_s)
        return await self.inner.initialize(frame, selection)

    async def update(self, frame: VisionFrame) -> TrackingResult:
        return await self.inner.update(frame)

    async def reset(self) -> None:
        await self.inner.reset()


class _SlowDetector:
    def __init__(self, inner: TargetDetector, delay_s: float) -> None:
        self.inner = inner
        self.delay_s = delay_s
        self.capability = inner.capability

    async def detect(self, frame: VisionFrame) -> tuple[Detection, ...]:
        await asyncio.sleep(self.delay_s)
        return tuple(await self.inner.detect(frame))


async def _prepare_direct_follow(
    service: VisionApplicationService,
) -> FollowConfiguration:
    frame = await service.capture_frame()
    assert frame is not None
    await service.select(
        frame_id=frame.frame_id,
        x=0.1,
        y=0.28,
        width=0.18,
        height=0.52,
    )
    status, profile, _ = await service.robot.get_motion_snapshot()
    assert status.connected
    angular = [
        item.joint_id for item in profile.joint_definitions if item.domain_unit is DomainUnit.DEG
    ]
    configuration = FollowConfiguration(
        dead_zone_x=0.08,
        dead_zone_y=0.08,
        ema_alpha=0.35,
        gain=0.5,
        max_step=2.0,
        max_rate=4.0,
        confidence_threshold=0.55,
        frame_freshness_limit_s=0.75,
        target_lost_limit_s=0.5,
        lease_ttl_s=2.0,
        mapping=FollowActuatorMapping(
            pan_joint=angular[0],
            tilt_joint=angular[1],
            pan_sign=1,
            tilt_sign=-1,
        ),
    )
    follow = await service.follow.start(
        FollowOperatorIntent(confirmed=True, configuration=configuration)
    )
    assert follow.state is FollowState.ACTIVE
    return configuration


@pytest.mark.parametrize("fault_kind", ["exception", "cross_frame"])
def test_tracker_fault_stops_active_follow_without_reusing_a_box(
    tmp_path: Path,
    fault_kind: str,
) -> None:
    async def scenario() -> None:
        app = make_app(tmp_path)
        service: VisionApplicationService = app.state.vision_service
        try:
            await app.state.robot_service.connect()
            await _prepare_direct_follow(service)
            capability = service.tracker.capability
            service.tracker = (
                _FaultingTracker(capability)
                if fault_kind == "exception"
                else _CrossFrameTracker(capability)
            )

            frame = await service.capture_frame()
            assert frame is not None
            assert service.follow.get_status().state is FollowState.STOPPED
            assert service.follow.get_status().stop_reason is FollowStopReason.TRACKER_FAULT
            assert service.follow.get_status().active_command_id is None
            snapshot = await service.status()
            assert snapshot.tracking is not None
            assert snapshot.tracking.bounding_box is None
        finally:
            await shutdown(app)

    asyncio.run(scenario())


def test_provider_initialization_and_detection_failures_are_structured(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = make_app(tmp_path)
        service: VisionApplicationService = app.state.vision_service
        try:
            frame = await service.capture_frame()
            assert frame is not None
            await service.select(
                frame_id=frame.frame_id,
                x=0.1,
                y=0.28,
                width=0.18,
                height=0.52,
            )
            service.person_detector = _FaultingDetector(service.person_detector.capability)
            before_detector_fault = await service.status()
            with pytest.raises(VisionProviderUnavailableError, match="detector failed"):
                await service.detect("person", frame.frame_id)
            after_detector_fault = await service.status()
            assert after_detector_fault.selection == before_detector_fault.selection
            assert after_detector_fault.tracking == before_detector_fault.tracking

            service.tracker = _FaultingTracker(service.tracker.capability)
            with pytest.raises(VisionProviderUnavailableError, match="failed to initialize"):
                await service.select(
                    frame_id=frame.frame_id,
                    x=0.2,
                    y=0.2,
                    width=0.2,
                    height=0.2,
                )
            failed = await service.status()
            assert failed.selection is None
            assert failed.tracking is not None
            assert failed.tracking.status.value == "FAULTED"
            assert failed.tracking.bounding_box is None

            service.tracker = _CrossFrameTracker(service.tracker.capability)
            with pytest.raises(
                VisionProviderUnavailableError,
                match="different frame",
            ):
                await service.select(
                    frame_id=frame.frame_id,
                    x=0.2,
                    y=0.2,
                    width=0.2,
                    height=0.2,
                )
            cross_frame = await service.status()
            assert cross_frame.selection is None
            assert cross_frame.tracking is not None
            assert cross_frame.tracking.status is TrackingStatus.FAULTED
            assert cross_frame.tracking.metadata == frame.metadata
            assert cross_frame.tracking.bounding_box is None
        finally:
            await shutdown(app)

    asyncio.run(scenario())


def test_slow_provider_results_are_rejected_after_frame_expiry(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_app(tmp_path)
        service: VisionApplicationService = app.state.vision_service
        try:
            service.frame_request_freshness_s = 0.05
            detector = service.person_detector
            service.person_detector = _SlowDetector(detector, 0.08)
            detector_frame = await service.capture_frame()
            assert detector_frame is not None
            with pytest.raises(VisionFrameConflictError):
                await service.detect("person", detector_frame.frame_id)

            tracker = service.tracker
            service.tracker = _SlowTracker(tracker, 0.08)
            tracker_frame = await service.capture_frame()
            assert tracker_frame is not None
            with pytest.raises(VisionFrameConflictError):
                await service.select(
                    frame_id=tracker_frame.frame_id,
                    x=0.1,
                    y=0.28,
                    width=0.18,
                    height=0.52,
                )
            snapshot = await service.status()
            assert snapshot.selection is None
            assert snapshot.tracking is not None
            assert snapshot.tracking.status.value == "STALE"
            assert snapshot.tracking.bounding_box is None
        finally:
            await shutdown(app)

    asyncio.run(scenario())


def test_stream_disconnect_releases_client_and_stops_follow(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_app(tmp_path)
        service: VisionApplicationService = app.state.vision_service
        try:
            await app.state.robot_service.connect()
            await _prepare_direct_follow(service)
            stream = service.stream_frames()
            assert await anext(stream) is not None
            assert service.active_streams == 1
            await stream.aclose()

            assert service.active_streams == 0
            follow = service.follow.get_status()
            assert follow.state is FollowState.STOPPED
            assert follow.stop_reason is FollowStopReason.BROWSER_DISCONNECTED
            assert follow.active_command_id is None
        finally:
            await shutdown(app)

    asyncio.run(scenario())


def test_cancelled_follow_start_cannot_leave_an_unpumped_active_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_app(tmp_path)
        service: VisionApplicationService = app.state.vision_service
        try:
            await app.state.robot_service.connect()
            configuration = await _prepare_direct_follow(service)
            first = service.follow.get_status()
            assert first.lease is not None
            await service.follow.stop(first.lease.lease_id)

            entered = asyncio.Event()

            async def blocked_initial_tracking(
                lease_id: object,
                result: TrackingResult,
            ) -> object:
                del lease_id, result
                entered.set()
                await asyncio.Event().wait()
                raise AssertionError("unreachable")

            monkeypatch.setattr(
                service.follow,
                "process_tracking",
                blocked_initial_tracking,
            )
            starting = asyncio.create_task(service.start_follow(configuration))
            await entered.wait()
            starting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await starting

            stopped = service.follow.get_status()
            assert stopped.state is FollowState.STOPPED
            assert stopped.stop_reason is FollowStopReason.BROWSER_DISCONNECTED
            assert stopped.active_command_id is None
        finally:
            await shutdown(app)

    asyncio.run(scenario())


def test_cancelled_explicit_stop_still_finishes_follow_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_app(tmp_path)
        service: VisionApplicationService = app.state.vision_service
        try:
            await app.state.robot_service.connect()
            await _prepare_direct_follow(service)
            active = service.follow.get_status()
            assert active.lease is not None
            original_stop = service.follow.stop
            entered = asyncio.Event()
            release = asyncio.Event()

            async def blocked_stop(lease_id: object) -> object:
                entered.set()
                await release.wait()
                return await original_stop(cast(Any, lease_id))

            monkeypatch.setattr(service.follow, "stop", blocked_stop)
            stopping = asyncio.create_task(service.stop_follow(active.lease.lease_id))
            await entered.wait()
            stopping.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await stopping

            stopped = service.follow.get_status()
            assert stopped.state is FollowState.STOPPED
            assert stopped.stop_reason is FollowStopReason.OPERATOR_STOP
            assert stopped.active_command_id is None
        finally:
            await shutdown(app)

    asyncio.run(scenario())


def test_camera_disconnect_stops_follow_and_capability_is_not_active(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = make_app(tmp_path)
        service: VisionApplicationService = app.state.vision_service
        try:
            await app.state.robot_service.connect()
            await _prepare_direct_follow(service)
            source = cast(SyntheticFrameSource, service.source)
            await source.disconnect()

            assert await service.capture_frame() is None
            follow = service.follow.get_status()
            assert follow.state is FollowState.STOPPED
            assert follow.stop_reason is FollowStopReason.CAMERA_DISCONNECTED
            snapshot = await service.status()
            assert snapshot.tracking is not None
            assert snapshot.tracking.status is TrackingStatus.FAULTED
            assert snapshot.tracking.bounding_box is None
            capabilities = await request(app, "GET", "/api/v1/vision/capabilities")
            assert capabilities.status_code == 200
            assert capabilities.json()["source"]["active"] is False
        finally:
            await shutdown(app)

    asyncio.run(scenario())


def test_source_exception_stops_follow_and_blocks_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_app(tmp_path)
        service: VisionApplicationService = app.state.vision_service
        try:
            await app.state.robot_service.connect()
            configuration = await _prepare_direct_follow(service)
            service.source = _FaultingSource(
                service.source.capability,
                service.source.source_id,
            )

            with pytest.raises(VisionProviderUnavailableError, match="frame source failed"):
                await service.capture_frame()
            assert service.follow.get_status().state is FollowState.STOPPED
            assert service.follow.get_status().stop_reason is FollowStopReason.CAMERA_DISCONNECTED
            snapshot = await service.status()
            assert snapshot.tracking is not None
            assert snapshot.tracking.status is TrackingStatus.FAULTED
            assert snapshot.tracking.bounding_box is None
            with pytest.raises(VisionFollowConflictError, match="source is unavailable"):
                await service.start_follow(configuration)
        finally:
            await shutdown(app)

    asyncio.run(scenario())
