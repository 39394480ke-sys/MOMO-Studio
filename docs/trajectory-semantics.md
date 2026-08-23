# Trajectory semantics

Stage 5 turns one stored Motion revision into one immutable, bounded Dry Run
`PreparedTrajectory`. A Motion is author intent; it is never executed directly. The
only executable value is the exact plan accepted by whole-path preflight and identified
by its SHA-256 digest.

## Inputs and bindings

Compilation binds the plan to the Motion UUID and revision, robot variant, active
Profile fingerprint, active provisional Kinematics fingerprint, exact start-state
sequence, sample rate, and every generated segment and sample. The active Joint state
must already equal the first keyframe within `1e-6` in each declared domain unit. Stage
5 does not insert an implicit move to the first keyframe.

All Joint membership and units come from `RobotProfile.enabled_joints`. V1 therefore
contains J11-J15; V2 contains J10-J15, with J10 in millimetres and the revolute joints
in degrees. Samples carry keyed domain values and explicit units. Kinematics conversion
to metres/radians remains confined to the named adapter boundary.

The plan digest covers every execution-relevant semantic value and excludes only the
non-semantic `compiled_at` wall-clock timestamp. A digest returned by an unsuccessful
preflight is always null. The prepared-plan cache is process-local, LRU-bounded to 16,
and holds the exact immutable objects; restart or eviction requires another preflight.

## Sampling and segment boundaries

The HTTP preflight surface accepts 5-50 Hz and defaults to 20 Hz. The compiler itself
has an explicit 1-100 Hz defensive bound. Each segment contributes
`ceil(duration * sample_rate)` intervals. The first sample occurs exactly at zero, the
last exactly at total duration, and adjacent segments share one boundary sample instead
of duplicating a timestamp. Sample time is strictly increasing.

The entire plan is rejected above any of these limits:

| Resource | Bound |
|---|---:|
| Total duration | 600 s |
| Total samples | 20,000 |
| Total segments | 2,000 |
| Cached prepared plans | 16 |
| Preview points per series/path | 1,000 |
| Playback rate | 0.25-2.0x |
| Loop traversals | 100 |

Compilation yields before every sampled FK/IK operation and at bounded dynamics
checkpoints, then checks a cooperative cancellation signal. Preflight is serialized and
latest-generation-wins: a newer request cancels/supersedes the current owner, and a
stale successful result cannot become READY or enter the cache. There is no request
queue, sample streaming endpoint, or unbounded retry. Cancellation latency is bounded
by the currently executing individual FK/IK call.

## Joint transitions and holds

The incoming transition belongs to its target keyframe. A Joint transition interpolates
every enabled Joint from the preceding compiled state to the target embedded snapshot.
The normalized interpolation parameter `u` uses:

| Easing | Curve |
|---|---|
| `LINEAR` | `u` |
| `SMOOTHSTEP` | `3u² - 2u³` |
| `EASE_IN_OUT` | `6u⁵ - 15u⁴ + 10u³` (quintic smootherstep) |

Endpoints remain exact. A keyframe hold is a separate stationary segment with elapsed
time, the same keyframe identity at both ends, no easing, and no position change.

Every compiled interval is checked against Profile logical limits, applicable
Calibration-derived raw reachability, and provisional velocity/acceleration limits.
The current Dry Run limits are 90 deg/s for revolute Joints, 100 mm/s for prismatic
Joints, 720 deg/s², and 800 mm/s² respectively. They are software bounds only and are
not physical validation.

## Cartesian-linear transitions

`CARTESIAN_LINEAR` has literal TCP-space meaning. Position follows a straight linear
path in millimetres. Orientation follows shortest-path normalized quaternion SLERP in
XYZW order; the implementation flips the target quaternion when necessary so the dot
product takes the shorter arc.

Every generated TCP sample is solved by IK and seeded from the previously accepted
Joint solution. The result is then rechecked using FK. A sample rejects the whole plan
if IK fails, a value is non-finite or outside logical/raw-derived limits, the target or
result is outside the bounded Dry Run workspace, FK/IK position residual exceeds 1 mm,
orientation residual exceeds 0.02 rad, or continuity exceeds 15 degrees/20 millimetres
per sample. No failed Cartesian segment is changed into Joint interpolation.

A redundant IK solution may reach the exact target TCP with Joint values different from
the target snapshot. That valid solved state is retained. A following segment begins
from the actual compiled Joint/TCP state, not from an unsolved embedded Joint value.

## Whole-plan preflight

Preflight returns named checks plus blocking violations with safe code, message, and
optional segment/sample/Joint evidence. Admission requires a supported Motion schema,
matching revision and variant, exact Profile/Kinematics fingerprints in every snapshot,
a matching fresh start-state sequence, a connected fresh robot, a compatible start
state and optional Calibration, a working Stop path, `DRY_RUN`, hardware access
`DISABLED`, and outstanding Real field acceptance.

All samples are compiled and checked before a digest or `PreparedTrajectory` is made
available. Preview reads a downsampled transport projection from that same plan. The
frontend never implements its own interpolation and the API never accepts client
samples, raw Servo values, driver selection, or hardware identifiers.

## Playback timing and state

Playback revalidates the exact prepared object immediately before execution. Motion
revision, variant, Profile, Kinematics, state sequence, connection, freshness, Stop
capability, hardware policy, and single-motion ownership must still match. Any change
requires a new preflight.

The Motion Safety Gateway owns one atomic admission coordinator across ordinary motion,
preflight, and playback. Final validation and owner claim occur under that coordinator,
so two paths cannot both observe a free slot and then claim separate executors. Play
rechecks the cached prepared object by identity and the latest preflight generation
after every await boundary and once more after the runner claim; eviction or superseding
preflight always rejects the stale caller and stops a just-claimed runner.

The coordinator's lifecycle epoch/count also fences Stop, Disconnect, and Shutdown.
Requests begun during a lifecycle transition fail immediately; requests whose epoch was
captured before it cannot later publish READY or claim execution. Stop cleanup has one
shielded owner, so caller cancellation cannot strand `STOPPING`; a repeated Stop joins
the same runner-join/state-flush/finalization task.

After preflight claims `PREFLIGHTING`, any lifecycle epoch mismatch invokes idempotent
Stop before returning the conflict. This keeps global Stop terminal precedence and
prevents cancellation from being mislabeled as a generic `FAULTED` preflight.

Motion mutations share a process-local lock with an exact execution revision lease.
Playback holds that lease from the fresh repository read through gateway validation and
the `PLAYING` transition. Update/delete before that transition rejects the stale plan;
update/delete after it cannot change the immutable samples already claimed.

The state machine is `IDLE`, `PREFLIGHTING`, `READY`, `PLAYING`, `PAUSED`, `STOPPING`,
`STOPPED`, `COMPLETED`, or `FAULTED`. Scheduling uses an injected monotonic clock and
absolute deadlines. Processing time cannot accumulate relative-sleep drift. When late,
the runner advances to the current logical sample instead of emitting an unsafe backlog
burst. Pause is acknowledged at a sample boundary and freezes logical elapsed time;
resume rebases the time anchor. Rate changes calculate current virtual trajectory time
from the prior anchor and rate before rebasing, so repeated changes cannot discard one
sample interval per change.

Looping is allowed only when the final and initial states are equal, so there is no
uncompiled endpoint-to-start jump. The duplicate loop boundary sample is skipped.
Looping is bounded and remains Stop-cancellable. Stop cancels validation, scheduled
sleep, pause waits, or in-flight Dry Run state application and has priority over normal
motion admission.

Stage 5 execution targets only a high-level Dry Run logical-state sink after the shared
Motion Safety Gateway. `STOPPED` means the in-memory Dry Run runner stopped; it is not a
physical emergency-stop claim. Real playback remains blocked pending Stage 8 and field
acceptance.

Playback faults expose only stable allowlisted validation codes or the fixed
`PLAYBACK_RUNTIME_FAULT` summary. Arbitrary exception text, tracebacks, secrets, and
absolute paths are not copied into HTTP, WebSocket, observer, or state-sink status.
