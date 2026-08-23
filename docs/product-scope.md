# Product scope

## Product definition

MOMO Studio is a local photography motion workstation for one active MOMO V1 or V2 robot. Its target workflow is:

`Connect → position in Joint or Cartesian mode → save Pose/add keyframe → arrange a timeline → choose transition, duration, hold, and easing → save Motion → manage in Library → preflight and play`

Stage 1 provides contracts and a runnable application shell only. It deliberately has no connection or movement capability.

## First-version capability boundary

| Area | Included in product direction | Stage 1 delivery |
|---|---|---|
| Robot control | V1/V2, connect/disconnect, Dry Run/Real, joint state, step/continuous jog, Move Joints, parameters, Home, Stop, software emergency-stop entry | Metadata only; no control endpoint or UI control |
| Kinematics | FK/IK, joint and Cartesian control, Base/Tool frames, Move Pose, reachability/error checks | Domain/port boundary only |
| Pose | Named snapshots containing keyed joints and canonical TCP, list/delete/Goto | Model, schema, example, repository port |
| Motion | Embedded keyframes, transitions, timeline, library, preflight, play/pause/resume/stop, loop/rate, interpolation/sampling, multi-turn safety, compatibility checks | Model, schema, example, repository port; no trajectory or playback |
| Vision | Camera feed for selection, manual box, object/face detection, following, center error, EMA, dead zone, stop on target loss | Provider port and placeholder page only |
| Device and safety | Calibration status, current-angle calibration, per-joint diagnostics, dependency/hardware checks, joint/raw/multi-turn limits, profile/calibration match | Safety rules and architecture boundary only |

## Product pages

The first version has exactly five primary pages: Control, Studio, Library, Vision, and Settings. Stage 1 makes every route render and labels unavailable functionality honestly. It does not show fake robot state or clickable movement controls.

## Explicitly out of scope

The first version does not include PyQt or another separate desktop GUI, AI dialogue or natural-language action control, voice agents or speech-to-text, gesture recognition, Cinematic Director or subject-lock directing, photography, video recording, movement-linked recording, a gripper, teach-by-dragging, a PyBullet product window, community functions, Camera Hub media management, or multi-arm product pages/coordination/synchronization/recording.

Vision may later display a camera stream solely for target selection and following. That does not create capture, recording, or media-library scope.

## Variants are product contracts

- V1: no linear rail; enabled joints are `j11`–`j15`.
- V2: linear rail present; enabled joints are `j10`–`j15`.

These are hardware variants, not application releases. Legacy contradictions are evidence to migrate, not authority to weaken the new contract.
