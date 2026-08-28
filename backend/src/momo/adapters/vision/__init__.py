"""Stage 7 vision adapters; importing this package never imports or opens OpenCV."""

from momo.adapters.vision.disabled_frame_source import DisabledFrameSource
from momo.adapters.vision.latest_frame_hub import LatestFrameHub, LatestFrameSubscription
from momo.adapters.vision.opencv_camera import (
    CameraAccessDeniedError,
    OpenCvCameraSource,
    OpenCvCameraSourceFactory,
    OperatorControlledOpenCvCameraSource,
    explicit_device_identifier,
)
from momo.adapters.vision.stream_encoder import PassthroughVisionStreamEncoder
from momo.adapters.vision.synthetic_detectors import (
    SyntheticFaceDetector,
    SyntheticPersonDetector,
    SyntheticTargetDetector,
)
from momo.adapters.vision.synthetic_frame_source import SyntheticFrameSource
from momo.adapters.vision.synthetic_scene import SyntheticVisionScenario
from momo.adapters.vision.synthetic_tracker import SyntheticTargetTracker
from momo.adapters.vision.unavailable import (
    UnavailableFaceDetector,
    UnavailableTargetDetector,
    UnavailableTargetTracker,
)

__all__ = [
    "CameraAccessDeniedError",
    "DisabledFrameSource",
    "LatestFrameHub",
    "LatestFrameSubscription",
    "OpenCvCameraSource",
    "OpenCvCameraSourceFactory",
    "OperatorControlledOpenCvCameraSource",
    "PassthroughVisionStreamEncoder",
    "SyntheticFaceDetector",
    "SyntheticFrameSource",
    "SyntheticPersonDetector",
    "SyntheticTargetDetector",
    "SyntheticTargetTracker",
    "SyntheticVisionScenario",
    "UnavailableFaceDetector",
    "UnavailableTargetDetector",
    "UnavailableTargetTracker",
    "explicit_device_identifier",
]
