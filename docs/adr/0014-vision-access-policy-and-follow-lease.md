# ADR 0014: Vision access policy and Follow lease

- Status: Accepted
- Date: 2026-08-24
- Stage: 7 — Vision and safe following

## Context

Vision introduces two capabilities that must stay independent: acquiring image frames
and turning a trustworthy tracking result into robot movement intent. Treating a page
visit, an installed imaging package, or a recent target box as implicit authority would
allow camera access or continued motion without a current operator decision.

The first version also needs deterministic browser and backend acceptance without a
camera or downloaded model. Optional live providers must remain honest when OpenCV or a
model is absent. Vision routes must preserve the existing rule that only the motion
application service and Motion Safety Gateway can admit executor work.

## Decision

### Camera access is an independent, deny-by-default policy

`CameraAccessPolicy` has three explicit values:

- `DISABLED` permits no frame source;
- `SYNTHETIC_ONLY` is the tracked default and permits only the deterministic in-memory
  source;
- `LIVE_CAMERA_ALLOWED` reserves an explicit live-camera grant but does not select or
  open a camera at startup.

The optional OpenCV factory requires all of the following before it imports `cv2`:
`LIVE_CAMERA_ALLOWED`, explicit local configuration, one explicit bounded device
identifier, and an explicit operator action. Constructing the source still performs no
device access; a separate explicit `open()` is the only path to `VideoCapture`. No
factory enumerates devices, probes a default camera, downloads a model, stores frames,
or records video.

Application startup selects the Synthetic source whenever camera access is not
`DISABLED`, including when the policy vocabulary is `LIVE_CAMERA_ALLOWED`. Stage 7 has
no route that invokes the optional live factory. Provider capability responses report
available/unavailable state, model source, notice, and reason without fabricating an
installed tracker or detector.

The Synthetic person/face detectors and target tracker operate only against the known
deterministic scene annotations. They are test/product fixtures, not a learned or
general-purpose object model.

### Every observation remains bound to one frame

Frames carry a validated `frame_id`, `source_id`, aware `captured_at`, dimensions,
media type, and bounded encoded content. A normalized box contains the same frame
identity and dimensions as well as finite in-frame `x`, `y`, `width`, and `height`.
Selection, detection, and tracking reject mismatched, unavailable, or expired frame
identity rather than rebasing coordinates onto the newest image.

For an active Follow, a different `frame_id` must have a strictly later
`captured_at`. A new ID with an equal or older timestamp is stale. A same-frame
`LOST` or low-confidence tracker correction is still accepted so it can cancel the
previous direction immediately.

### Follow is explicit, leased, bounded, and Dry Run only

Starting Follow requires confirmed operator intent and a complete bounded
`FollowConfiguration`. The actuator mapping names distinct pan and tilt joints, signs,
and `VERIFIED_FOR_DRY_RUN` status. Both mapped joints must be present in the active
Profile's explicit `enabled_joints` and must be `REVOLUTE` joints in `deg`; a rail or
unknown joint cannot be repurposed as pan/tilt.

The pure controller computes normalized center error, EMA, dead zone, configured
sign/gain, maximum step, and time-based maximum rate. It emits an incremental
high-level `VISION` + `MOVE_JOINTS` intent against the latest robot snapshot. A
`VisionCommandCoordinator` may call only the injected motion application/gateway-facing
protocol. It never imports or calls an executor, driver, Servo adapter, or raw device
API. Every accepted command therefore reuses the Motion Safety Gateway and the shared
single-motion slot.

Only one Follow lease may be active. Heartbeat renews its bounded expiry. Stale frames,
target loss, low confidence, camera disconnect, tracker fault, browser disconnect,
backend shutdown, robot disconnect/fault/staleness, motion conflict/rejection, lease
expiry, operator Stop, and Global Stop all stop ownership. Target loss or low confidence
first suspends/cancels the active Vision command so the last direction cannot continue
during the bounded lost-target grace period.

Start, Stop, Global Stop, and shutdown use lifecycle epochs so a start awaiting a robot
snapshot cannot publish a lease after a concurrent lifecycle barrier. Global Stop's
hook invalidates Follow without re-entering motion cancellation while the motion
service holds admission locks; the global motion owner has already been cancelled.
Backend shutdown permanently closes the Follow service and rejects later starts.

### Frame delivery is latest-value and bounded

The local stream is pull-paced and `no-store`. Slow consumers do not receive an
unbounded queue: fan-out retains one latest frame and the application retains at most 64
recent frames subject to a 32 MiB aggregate content cap. Stream clients are bounded and
disconnect cleanup releases the client and stops an active Follow lease. No frame is
persisted and no Vision WebSocket or alternate motion transport is added.

## Consequences

- Stage 7 can be verified end to end with Synthetic frames and Dry Run motion without a
  camera, physical robot, OpenCV installation, model download, or captured media.
- Real Follow remains blocked until camera behavior, Profile mapping, Kinematics,
  Calibration, motion outcomes, operator/session policy, and field acceptance are all
  independently verified.
- Installing OpenCV later is insufficient to activate live capture. A reviewed explicit
  composition/use case and provenance review are still required.
- Latest-value delivery deliberately drops intermediate frames for a slow client; this
  is safer than accumulating delayed control observations.

## Rejected alternatives

- Opening the default camera on backend startup or Vision-page load.
- Enumerating camera devices to choose one automatically.
- Treating the Synthetic detector/tracker as a general model.
- Downloading detector weights or cascades at runtime.
- Using a frontend-only heartbeat or pointer event as the Follow safety guarantee.
- Reusing the last target direction after loss.
- Hard-coding `j10`, `j11`, `j15`, `arm_a`, or a fixed six-joint mapping.
- Dispatching from a Vision route/controller directly to a driver or executor.
