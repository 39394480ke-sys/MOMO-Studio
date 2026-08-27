# Product scope

## Product definition

MOMO Studio is a local photography motion workstation for one active MOMO V1 or V2 robot. Its target workflow is:

`Connect → position in Joint or Cartesian mode → save Pose/add keyframe → arrange a timeline → choose transition, duration, hold, and easing → save Motion → manage in Library → preflight and play`

The product is delivered in evidence-backed Stages. Completed work through Stage 7
provides Dry Run control, kinematics, Library, trajectory preflight/preview/playback,
Studio authoring, and Synthetic Vision/Follow. Stage 8 implements the separately gated
Real-hardware, Calibration, security, backup/recovery, and release-candidate software
boundary. Its final combined software gates, Dry Run browser acceptance, and independent
audit pass; only dedicated Git delivery and physical field acceptance remain separate
closeout items. No physical acceptance is implied.

## First-version capability boundary

| Area | Included in product direction | Current evidence |
|---|---|---|
| Robot control | V1/V2, connect/disconnect, Dry Run/Real, joint state, step/continuous jog, Move Joints, parameters, Home, Stop, software emergency-stop entry | Dry Run lifecycle/control complete; multi-factor Real software boundary implemented but default/field use blocked |
| Kinematics | FK/IK, joint and Cartesian control, Base/Tool frames, Move Pose, reachability/error checks | Provisional Dry Run FK/IK/control complete |
| Pose | Named snapshots containing keyed joints and canonical TCP, list/delete/Goto | Versioned atomic Library/Capture/Goto complete |
| Motion | Embedded keyframes, transitions, timeline, library, preflight, play/pause/resume/stop, loop/rate, interpolation/sampling, multi-turn safety, compatibility checks | Formal Library, deterministic preflight/preview/Playback, and Studio Draft/edge/autosave/Save/Goto complete through Stage 6 |
| Vision | Camera feed for selection, manual box, object/face detection, following, center error, EMA, dead zone, stop on target loss | Synthetic source/fixture detectors/tracker and Dry Run Follow are complete; a separately gated explicit-ID real-camera preview is read-only, while live tracking and Real Follow remain blocked |
| Device and safety | Calibration status, current-angle calibration, per-joint diagnostics, dependency/hardware checks, joint/raw/multi-turn limits, profile/calibration match | Fake-only gated readiness/diagnostics/Calibration/executor software implemented; Feetech and physical acceptance pending |
| Security and recovery | Loopback/LAN policy, REST/WebSocket/Vision auth, bounded audit, backup/preview/migration/restore | Local default, strict same-host HTTP LAN Origin, structured redaction, and WAL startup recovery implemented; deployment/field exercise pending |

## Product pages

The first version has exactly five primary pages: Control, Studio, Library, Vision, and
Settings. Every route renders and labels unavailable functionality honestly. Control,
Library/Playback, Studio, and Vision are backend-driven. Settings shows LAN
session controls, Real readiness blockers, masked device evidence, diagnostics, and the
protected Calibration workflow without fabricating availability. The persistent release
banner says `MOMO Studio 0.1.0-rc1`, `Dry Run validated`, and `Real hardware field
acceptance pending`. The Vision page labels the optional live source `READ ONLY CAMERA`
and does not fabricate tracking, recording, Feetech, or Real readiness.

## Explicitly out of scope

The first version does not include PyQt or another separate desktop GUI, AI dialogue or natural-language action control, voice agents or speech-to-text, gesture recognition, Cinematic Director or subject-lock directing, photography, video recording, movement-linked recording, a gripper, teach-by-dragging, a PyBullet product window, community functions, Camera Hub media management, or multi-arm product pages/coordination/synchronization/recording.

Vision displays a local Synthetic stream for target selection and Dry Run Follow. Its
optional real-camera stream is separately gated and preview-only. Neither capability
creates photography, recording, or media-library scope. Backup accepts uploaded bytes,
not a browser-selected server path, and same-backend SPA hosting does not create a
second GUI.

## Variants are product contracts

- V1: no linear rail; enabled joints are `j11`–`j15`.
- V2: linear rail present; enabled joints are `j10`–`j15`.

These are hardware variants, not application releases. Legacy contradictions are evidence to migrate, not authority to weaken the new contract.
