# ADR 0020: Operator-controlled read-only live camera

Status: Accepted for the post-`0.1.0-rc1` read-only camera acceptance slice.

## Context

The validated candidate exposed deterministic Synthetic Vision only. During operator
acceptance, an explicitly connected Osmo Pocket 3 produced no real picture because the
product intentionally had no route that could open a camera. The next safe increment is
visibility, not automation: prove that MOMO Studio can acquire and release real frames
without enabling robot motion, tracking, recording, or Real Follow.

## Decision

The tracked default remains `SYNTHETIC_ONLY`. Live composition requires all of:

- `camera_access_policy: LIVE_CAMERA_ALLOWED`;
- one explicit bounded `live_camera_device_id`;
- `live_camera_local_config_enabled: true` in the selected ignored local file; and
- a later HTTP open request containing the literal read-only confirmation.

Environment values alone cannot provide the local-file grant. The device ID is never
accepted by an API, returned in capabilities, logged as frame identity, or committed.
No code enumerates cameras or probes a default device.

Startup composes an `OperatorControlledFrameSource` in `CLOSED`. Construction and status
reads perform no `cv2` import and no `VideoCapture`. The explicit open operation lazily
imports the optional `opencv-python-headless` package, opens exactly the configured ID,
applies bounded width/height/FPS requests, captures and JPEG-encodes a first frame, and
reports success only then. Failure releases the handle and reports a structured provider
error.

The live source is preview-only. Manual ROI, person/face detection, tracking, Follow,
and all recording/persistence behavior are unavailable in both UI and application
service. Frames use the existing bounded in-memory latest/history limits and no-store
HTTP transport. Closing uses priority authorization, completes release despite request
cancellation, and clears transient Vision state. Backend shutdown also releases the
source.

## Consequences

- Operators can verify the real camera picture without granting any real robot action.
- Camera access is visible and reversible, but it remains separate from Real Vision
  Follow field acceptance.
- The optional camera dependency expands local installation and distribution review;
  the normal installation and safe defaults remain camera-free.
- Selecting a device is an external operator task. MOMO Studio deliberately provides no
  scan, enumeration, default-camera fallback, device chooser, or persisted media.
- Future detection, tracking, recording, or Follow work requires a separate decision,
  provider provenance, resource bounds, UI design, tests, and physical safety evidence.

## Rejected alternatives

- Opening the camera during backend startup or when the Vision page mounts.
- Letting the browser submit an arbitrary device ID.
- Enumerating devices and silently choosing the first available camera.
- Reusing Synthetic selection/tracking semantics against live frames.
- Treating successful preview as evidence for Real Follow or robot motion.
