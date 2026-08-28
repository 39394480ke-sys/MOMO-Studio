"""Focused Stage 7 domain/port/adapter evidence without real camera access."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import cast

import pytest
from pydantic import ValidationError

from momo.adapters.vision import (
    CameraAccessDeniedError,
    DisabledFrameSource,
    LatestFrameHub,
    OpenCvCameraSourceFactory,
    OperatorControlledOpenCvCameraSource,
    PassthroughVisionStreamEncoder,
    SyntheticFaceDetector,
    SyntheticFrameSource,
    SyntheticPersonDetector,
    SyntheticTargetTracker,
    UnavailableFaceDetector,
    UnavailableTargetDetector,
    UnavailableTargetTracker,
    explicit_device_identifier,
)
from momo.domain.errors import VisionProviderUnavailableError
from momo.domain.vision import (
    CameraAccessPolicy,
    FrameMetadata,
    NormalizedBoundingBox,
    TargetKind,
    TargetSelection,
    TrackingStatus,
    VisionProviderStatus,
    VisionStatus,
)
from momo.ports.vision import FaceDetector, FrameSource, TargetDetector, TargetTracker


class FakeClock:
    def __init__(self) -> None:
        self.elapsed = 0.0
        self.sleeps: list[float] = []
        self.started_at = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)

    def monotonic(self) -> float:
        return self.elapsed

    def now(self) -> datetime:
        return self.started_at + timedelta(seconds=self.elapsed)

    async def sleep(self, delay_s: float) -> None:
        delay = max(0.0, delay_s)
        self.sleeps.append(delay)
        self.elapsed += delay


def metadata(*, frame_id: str = "synthetic-00000001") -> FrameMetadata:
    return FrameMetadata(
        frame_id=frame_id,
        source_id="synthetic",
        captured_at=datetime(2026, 8, 24, 8, 0, tzinfo=UTC),
        width_px=640,
        height_px=360,
    )


def box(frame_metadata: FrameMetadata | None = None) -> NormalizedBoundingBox:
    return NormalizedBoundingBox.from_metadata(
        x=0.1,
        y=0.2,
        width=0.3,
        height=0.4,
        metadata=frame_metadata or metadata(),
    )


def source_status(source: FrameSource) -> VisionStatus:
    """Read through the mutable source boundary so mypy does not retain narrowing."""

    return source.status


def test_normalized_box_is_strict_frame_bound_and_maps_pixels() -> None:
    value = box()

    assert value.center_x == pytest.approx(0.25)
    assert value.center_y == pytest.approx(0.4)
    assert value.metadata == metadata()
    assert value.to_pixels() == (64, 72, 192, 144)
    assert (
        NormalizedBoundingBox.from_pixels(
            x_px=64,
            y_px=72,
            width_px=192,
            height_px=144,
            metadata=metadata(),
        )
        == value
    )

    for changes in (
        {"width": 0.0},
        {"height": -0.1},
        {"x": -0.01},
        {"x": 0.8, "width": 0.3},
        {"y": 0.8, "height": 0.3},
        {"x": float("nan")},
        {"width": float("inf")},
    ):
        with pytest.raises(ValidationError):
            value.model_copy(update=changes).model_validate(
                {**value.model_dump(mode="python"), **changes}
            )


def test_frame_metadata_requires_aware_time_and_bounded_dimensions() -> None:
    base = metadata().model_dump(mode="python")
    with pytest.raises(ValidationError, match="timezone"):
        FrameMetadata.model_validate({**base, "captured_at": datetime(2026, 8, 24)})
    with pytest.raises(ValidationError, match="resolution"):
        FrameMetadata.model_validate({**base, "width_px": 1920, "height_px": 1200})
    with pytest.raises(ValidationError):
        FrameMetadata.model_validate({**base, "frame_id": ""})


def test_synthetic_source_is_deterministic_pull_paced_and_bounded() -> None:
    async def scenario() -> None:
        clock_a = FakeClock()
        source_a = SyntheticFrameSource(
            clock=clock_a,
            width_px=64,
            height_px=48,
            fps=10.0,
            delay_s=0.25,
            disconnect_after_frames=2,
        )
        first = await source_a.latest_frame()
        second = await source_a.latest_frame()
        disconnected = await source_a.latest_frame()

        assert first is not None and second is not None
        assert first.frame_id == "synthetic-00000001"
        assert second.frame_id == "synthetic-00000002"
        assert first.content.startswith(b"\x89PNG")
        assert second.captured_at - first.captured_at >= timedelta(seconds=0.25)
        assert clock_a.elapsed >= 0.5
        assert disconnected is None
        assert source_a.status is VisionStatus.DISCONNECTED

        clock_b = FakeClock()
        source_b = SyntheticFrameSource(
            clock=clock_b,
            width_px=64,
            height_px=48,
            fps=10.0,
            delay_s=0.25,
        )
        replay = await source_b.latest_frame()
        assert replay == first

        rate_clock = FakeClock()
        rate_source = SyntheticFrameSource(
            clock=rate_clock,
            width_px=64,
            height_px=48,
            fps=5.0,
        )
        rate_first = await rate_source.latest_frame()
        rate_second = await rate_source.latest_frame()
        assert rate_first is not None and rate_second is not None
        assert rate_second.captured_at - rate_first.captured_at == timedelta(seconds=0.2)

        await source_a.aclose()
        assert source_status(source_a) is VisionStatus.CLOSED

    asyncio.run(scenario())

    with pytest.raises(ValueError, match="at most"):
        SyntheticFrameSource(fps=31.0)
    with pytest.raises(ValueError, match="resolution"):
        SyntheticFrameSource(width_px=1920, height_px=1200)


def test_synthetic_detectors_are_honest_fixture_capabilities_and_support_loss() -> None:
    async def scenario() -> None:
        source = SyntheticFrameSource(
            clock=FakeClock(),
            width_px=64,
            height_px=48,
            lost_frame_numbers={2},
        )
        person = SyntheticPersonDetector(scenario=source.scenario)
        face = SyntheticFaceDetector(scenario=source.scenario)
        first = await source.latest_frame()
        lost = await source.latest_frame()
        assert first is not None and lost is not None

        people = await person.detect(first)
        faces = await face.detect(first)
        assert len(people) == 1 and people[0].target_kind is TargetKind.PERSON
        assert len(faces) == 1 and faces[0].target_kind is TargetKind.FACE
        assert person.capability.model_source == "MOMO deterministic synthetic fixture"
        assert "not a general-purpose" in person.capability.notice
        assert await person.detect(lost) == ()
        assert await face.detect(lost) == ()

        empty = first.model_copy(update={"content": b""})
        assert await person.detect(empty) == ()

    asyncio.run(scenario())


def test_synthetic_tracker_init_update_stale_lost_and_reset() -> None:
    async def scenario() -> None:
        source = SyntheticFrameSource(
            clock=FakeClock(),
            width_px=64,
            height_px=48,
            lost_frame_numbers={3},
        )
        detector = SyntheticPersonDetector(scenario=source.scenario)
        tracker = SyntheticTargetTracker(scenario=source.scenario)
        first = await source.latest_frame()
        second = await source.latest_frame()
        third = await source.latest_frame()
        assert first is not None and second is not None and third is not None
        detection = (await detector.detect(first))[0]
        selection = TargetSelection(
            bounding_box=detection.bounding_box,
            target_kind=TargetKind.PERSON,
        )

        initialized = await tracker.initialize(first, selection)
        stale = await tracker.update(first)
        locked = await tracker.update(second)
        lost = await tracker.update(third)

        assert initialized.status is TrackingStatus.LOCKED
        assert stale.status is TrackingStatus.STALE and stale.bounding_box is None
        assert locked.status is TrackingStatus.LOCKED
        assert locked.bounding_box is not None
        assert locked.bounding_box.frame_id == second.frame_id
        assert lost.status is TrackingStatus.LOST and lost.confidence == 0.0
        await tracker.reset()
        assert (await tracker.update(third)).status is TrackingStatus.UNINITIALIZED

    asyncio.run(scenario())


def test_tracker_rejects_selection_from_a_different_frame() -> None:
    async def scenario() -> None:
        source = SyntheticFrameSource(clock=FakeClock(), width_px=64, height_px=48)
        tracker = SyntheticTargetTracker(scenario=source.scenario)
        first = await source.latest_frame()
        second = await source.latest_frame()
        assert first is not None and second is not None
        selection = TargetSelection(bounding_box=box(first.metadata))
        result = await tracker.initialize(second, selection)
        assert result.status is TrackingStatus.STALE
        assert result.bounding_box is None

    asyncio.run(scenario())


def test_unavailable_detector_and_tracker_never_fake_capability() -> None:
    async def scenario() -> None:
        source = SyntheticFrameSource(clock=FakeClock(), width_px=64, height_px=48)
        frame = await source.latest_frame()
        assert frame is not None
        detector = UnavailableTargetDetector()
        face = UnavailableFaceDetector()
        tracker = UnavailableTargetTracker()

        assert detector.capability.status is VisionProviderStatus.UNAVAILABLE
        assert face.capability.status is VisionProviderStatus.UNAVAILABLE
        assert tracker.capability.status is VisionProviderStatus.UNAVAILABLE
        with pytest.raises(VisionProviderUnavailableError):
            await detector.detect(frame)
        with pytest.raises(VisionProviderUnavailableError):
            await face.detect(frame)
        fault = await tracker.initialize(frame, TargetSelection(bounding_box=box(frame.metadata)))
        assert fault.status is TrackingStatus.FAULTED
        assert fault.bounding_box is None

    asyncio.run(scenario())


def test_latest_frame_hub_has_one_slot_skips_backlog_and_releases_subscriber() -> None:
    async def scenario() -> None:
        source = SyntheticFrameSource(clock=FakeClock(), width_px=64, height_px=48)
        first = await source.latest_frame()
        second = await source.latest_frame()
        third = await source.latest_frame()
        assert first is not None and second is not None and third is not None
        hub = LatestFrameHub(max_subscribers=1)
        subscription = await hub.subscribe(replay_latest=False)
        assert hub.subscriber_count == 1
        with pytest.raises(RuntimeError, match="limit"):
            await hub.subscribe()

        await hub.publish(first)
        await hub.publish(second)
        await hub.publish(third)
        assert await anext(subscription) == third
        await subscription.aclose()
        assert hub.subscriber_count == 0
        await hub.aclose()
        assert hub.latest is None

    asyncio.run(scenario())


def test_disabled_source_and_stream_encoder_fail_closed_without_storage() -> None:
    async def scenario() -> None:
        disabled = DisabledFrameSource()
        assert isinstance(disabled, FrameSource)
        assert disabled.status is VisionStatus.DISABLED
        assert disabled.capability.status is VisionProviderStatus.UNAVAILABLE
        assert await disabled.latest_frame() is None
        await disabled.aclose()
        assert source_status(disabled) is VisionStatus.CLOSED

        source = SyntheticFrameSource(clock=FakeClock(), width_px=64, height_px=48)
        frame = await source.latest_frame()
        assert frame is not None
        encoder = PassthroughVisionStreamEncoder()
        assert encoder.encode(frame) is frame.content
        with pytest.raises(ValueError, match="does not match"):
            PassthroughVisionStreamEncoder(media_type="image/jpeg").encode(frame)

    asyncio.run(scenario())


class _FakeImage:
    shape = (48, 64, 3)


class _FakeEncoded:
    def tobytes(self) -> bytes:
        return b"fake-jpeg"


class _FakeCapture:
    def __init__(self) -> None:
        self.released = False
        self.settings: list[tuple[int, float]] = []

    def isOpened(self) -> bool:
        return True

    def read(self) -> tuple[bool, _FakeImage]:
        return True, _FakeImage()

    def set(self, property_id: int, value: float) -> bool:
        self.settings.append((property_id, value))
        return True

    def release(self) -> None:
        self.released = True


class _FakeCv2(ModuleType):
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FPS = 5

    def __init__(self) -> None:
        super().__init__("cv2")
        self.capture_calls: list[str | int] = []
        self.capture = _FakeCapture()

    def VideoCapture(self, device_identifier: str | int) -> _FakeCapture:
        self.capture_calls.append(device_identifier)
        return self.capture

    def imencode(self, extension: str, image: _FakeImage) -> tuple[bool, _FakeEncoded]:
        assert extension == ".jpg"
        assert image.shape == (48, 64, 3)
        return True, _FakeEncoded()


def test_opencv_factory_is_lazy_policy_first_and_constructor_does_not_open() -> None:
    async def scenario() -> None:
        fake_cv2 = _FakeCv2()
        imports: list[str] = []

        def importer(name: str) -> ModuleType:
            imports.append(name)
            return cast(ModuleType, fake_cv2)

        factory = OpenCvCameraSourceFactory(importer=importer)
        assert imports == []
        assert fake_cv2.capture_calls == []

        with pytest.raises(CameraAccessDeniedError):
            factory.create(
                camera_access_policy=CameraAccessPolicy.SYNTHETIC_ONLY,
                local_config_enabled=True,
                device_identifier="explicit-device",
                operator_action=True,
            )
        assert imports == []
        assert fake_cv2.capture_calls == []

        source = factory.create(
            camera_access_policy=CameraAccessPolicy.LIVE_CAMERA_ALLOWED,
            local_config_enabled=True,
            device_identifier="explicit-device",
            operator_action=True,
            clock=FakeClock(),
            max_fps=15.0,
        )
        assert imports == ["cv2"]
        assert fake_cv2.capture_calls == []
        await source.open()
        assert fake_cv2.capture_calls == ["explicit-device"]
        assert fake_cv2.capture.settings == [(3, 1280.0), (4, 720.0), (5, 15.0)]
        frame = await source.latest_frame()
        assert frame is not None
        assert frame.media_type == "image/jpeg"
        assert frame.content == b"fake-jpeg"
        await source.aclose()
        assert fake_cv2.capture.released is True

    asyncio.run(scenario())


def test_operator_controlled_opencv_source_defers_import_and_device_open() -> None:
    async def scenario() -> None:
        fake_cv2 = _FakeCv2()
        imports: list[str] = []
        importer_threads: list[int] = []
        event_loop_thread = threading.get_ident()

        def importer(name: str) -> ModuleType:
            imports.append(name)
            importer_threads.append(threading.get_ident())
            return cast(ModuleType, fake_cv2)

        source = OperatorControlledOpenCvCameraSource(
            camera_access_policy=CameraAccessPolicy.LIVE_CAMERA_ALLOWED,
            local_config_enabled=True,
            device_identifier=1,
            clock=FakeClock(),
            max_fps=30.0,
            width_px=1280,
            height_px=720,
            factory=OpenCvCameraSourceFactory(importer=importer),
        )
        assert source.status is VisionStatus.CLOSED
        assert imports == []
        assert fake_cv2.capture_calls == []

        await source.open()
        assert imports == ["cv2"]
        assert importer_threads != [event_loop_thread]
        assert fake_cv2.capture_calls == [1]
        frame = await source.latest_frame()
        assert frame is not None
        assert frame.media_type == "image/jpeg"
        assert source_status(source) is VisionStatus.STREAMING

        await source.aclose()
        assert fake_cv2.capture.released is True
        assert source.status is VisionStatus.CLOSED

    asyncio.run(scenario())


def test_explicit_camera_identifier_parses_only_canonical_bounded_indexes() -> None:
    assert explicit_device_identifier("0") == 0
    assert explicit_device_identifier(" 1 ") == 1
    assert explicit_device_identifier("01") == "01"
    assert explicit_device_identifier("camera-path") == "camera-path"

    with pytest.raises(ValueError, match="between 0 and 64"):
        explicit_device_identifier("65")


def test_public_ports_are_structurally_implemented() -> None:
    source = SyntheticFrameSource(clock=FakeClock(), width_px=64, height_px=48)
    person = SyntheticPersonDetector()
    face = SyntheticFaceDetector()
    tracker = SyntheticTargetTracker()

    assert isinstance(source, FrameSource)
    assert isinstance(person, TargetDetector)
    assert isinstance(face, FaceDetector)
    assert isinstance(tracker, TargetTracker)
