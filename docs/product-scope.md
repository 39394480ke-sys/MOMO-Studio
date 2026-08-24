# Product scope

## Product definition

MOMO Studio is a local photography motion workstation for one active MOMO V1 or V2 robot. Its target workflow is:

`Connect → position in Joint or Cartesian mode → save Pose/add keyframe → arrange a timeline → choose transition, duration, hold, and easing → save Motion → manage in Library → preflight and play`

The product is delivered in evidence-backed Stages. Completed work through Stage 6
provides Dry Run control, kinematics, Library, trajectory preflight/preview/playback,
and Studio authoring. Stage 7 Vision/Follow implementation, browser acceptance, and
final independent audit P1=0/P2=0 are green; dedicated commit/push remains Pending.
The Real boundary remains separately gated Stage 8 work.

## First-version capability boundary

| Area | Included in product direction | Current evidence |
|---|---|---|
| Robot control | V1/V2, connect/disconnect, Dry Run/Real, joint state, step/continuous jog, Move Joints, parameters, Home, Stop, software emergency-stop entry | Dry Run lifecycle/control complete; Real remains blocked |
| Kinematics | FK/IK, joint and Cartesian control, Base/Tool frames, Move Pose, reachability/error checks | Provisional Dry Run FK/IK/control complete |
| Pose | Named snapshots containing keyed joints and canonical TCP, list/delete/Goto | Versioned atomic Library/Capture/Goto complete |
| Motion | Embedded keyframes, transitions, timeline, library, preflight, play/pause/resume/stop, loop/rate, interpolation/sampling, multi-turn safety, compatibility checks | Formal Library, deterministic preflight/preview/Playback, and Studio Draft/edge/autosave/Save/Goto complete through Stage 6 |
| Vision | Camera feed for selection, manual box, object/face detection, following, center error, EMA, dead zone, stop on target loss | Synthetic source/fixture detectors/tracker, frame-bound ROI, bounded stream, and lease-bound Dry Run Follow implemented; Stage 7 browser/audit green and delivery pending; live camera and Real Follow blocked |
| Device and safety | Calibration status, current-angle calibration, per-joint diagnostics, dependency/hardware checks, joint/raw/multi-turn limits, profile/calibration match | Safety rules and architecture boundary only |

## Product pages

The first version has exactly five primary pages: Control, Studio, Library, Vision, and
Settings. Every route renders and labels unavailable functionality honestly. Through
Stage 6, Control, Library/Playback, and Studio are backend-driven. Stage 7 replaces the
Vision placeholder with a Synthetic provider workspace for manual ROI, fixture
detection/tracking, and lease-bound Dry Run Follow. It displays unavailable optional
providers and the Real block reason honestly; no page fabricates live-camera or Real
readiness.

## Explicitly out of scope

The first version does not include PyQt or another separate desktop GUI, AI dialogue or natural-language action control, voice agents or speech-to-text, gesture recognition, Cinematic Director or subject-lock directing, photography, video recording, movement-linked recording, a gripper, teach-by-dragging, a PyBullet product window, community functions, Camera Hub media management, or multi-arm product pages/coordination/synchronization/recording.

Vision displays a local Synthetic stream solely for target selection and following.
Optional live capture remains separately gated. Neither capability creates photography,
recording, or media-library scope.

## Variants are product contracts

- V1: no linear rail; enabled joints are `j11`–`j15`.
- V2: linear rail present; enabled joints are `j10`–`j15`.

These are hardware variants, not application releases. Legacy contradictions are evidence to migrate, not authority to weaken the new contract.
