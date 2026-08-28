# ADR 0012: Compiled trajectory identity and playback admission

- Status: Accepted
- Date: 2026-08-24

## Context

A stored Motion is author intent, not an executable stream. Joint and Cartesian
segments require deterministic sampling, full-path kinematic and dynamic checks, and
explicit holds before any state is applied. Recompiling after preflight, or executing a
plan after the active robot, Motion revision, Profile, or Kinematics model changes,
would separate the reviewed evidence from the work that actually runs.

The pinned Legacy playback code used mutable pause/stop flags, wall-clock sleeps,
implicit file/controller access, direct controller calls, ordered Joint arrays, a
`j10` unit assumption, and optional raw/multi-turn replay. Those are characterization
facts only. Its architecture, timing loop, raw state, and safety values are not reused.

## Decision

Stage 5 introduces immutable `TrajectoryPlan`, `TrajectorySegment`,
`TrajectorySample`, `TrajectoryPreflightReport`, `TrajectoryViolation`, and
`PreparedTrajectory` contracts. A plan binds all of the following:

- Motion UUID and revision;
- robot variant and exact enabled Joint/unit set;
- Profile and Kinematics fingerprints;
- active start-state sequence;
- bounded sample rate and duration;
- ordered, finite samples and segment metadata;
- a deterministic SHA-256 digest.

The digest is computed from a canonical semantic payload. It excludes wall-clock
`compiled_at`, so identical inputs and configuration produce the same digest. The
prepared value is deeply immutable. Preview reads a bounded representation of that same
plan; it does not compile a second plan.

Joint segments support `LINEAR`, `SMOOTHSTEP`, and `EASE_IN_OUT`. The compiler samples
all explicitly enabled Joints, represents keyframe holds as stationary time-bearing
segments, emits one shared boundary sample rather than duplicate zero-work samples, and
checks monotonic time, exact endpoints, duration, logical/raw-derived limits, velocity,
and acceleration.

`CARTESIAN_LINEAR` means TCP-space interpolation: position is linear and orientation
uses shortest-path quaternion SLERP. Every intermediate TCP sample is solved by IK with
the previous accepted Joint sample as its seed, then checked for residual, workspace,
limits, and Joint continuity. Any intermediate failure rejects the complete preflight.
Cartesian motion never falls back to Joint interpolation.

Compilation has fixed workstation budgets, including sample-rate, duration, segment,
and total-sample ceilings. It yields to the application event loop before every sampled
FK/IK operation and at bounded dynamics checkpoints, then checks cooperative
cancellation. One latest-generation preflight owns compilation; a newer request or
lifecycle Stop cancels/supersedes the old generation, and a stale result cannot publish
READY or enter the cache. It performs no hardware or filesystem access.

The application retains a bounded cache of successful prepared trajectories. Playback
requires the exact digest returned by preflight and revalidates Motion revision, active
variant, Profile fingerprint, Kinematics fingerprint, start-state sequence, robot
freshness, stop capability, Dry Run policy, and single-motion ownership immediately
before dispatch. A changed fact rejects playback and requires a new preflight. No route
may supply trajectory samples.

Playback uses an injected monotonic Clock and absolute deadlines. Its state machine is:

```text
IDLE -> PREFLIGHTING -> READY -> PLAYING
                                 |  |
                                 |  +-> PAUSED -> PLAYING
                                 +----> STOPPING -> STOPPED
                                 +----> COMPLETED
                                 +----> FAULTED
```

Pause freezes the current sample and logical elapsed time. Resume rebases the deadline
and skips overdue indices rather than emitting a backlog. Rate is bounded to 0.25-2.0x
and changes rebase at current virtual trajectory time, preserving integrated-time
continuity across repeated changes. Loop is explicit and remains cancellable.
Stop owns the highest-priority cancellation signal. Only one playback or ordinary motion
may be active.

Prepared trajectory admission is an extension of the existing application-level Motion
Safety Gateway, not a parallel raw-control path. Execution targets only the high-level
Dry Run motion-state port in Stage 5. The REST API accepts Motion identity, expected
revision, prepared digest, loop, and rate; it never accepts a driver, register, serial
port, raw Servo value, or arbitrary sample array. Runtime faults publish only stable
public codes; exception text, paths, credentials, and tracebacks never enter playback
status or the state sink. The existing read-only robot WebSocket publishes typed
playback status but accepts no commands. Preview stays on the application event loop,
so its LRU touch cannot race cache mutation in a FastAPI worker thread.

One gateway-owned admission coordinator serializes the final check-and-claim transition
for ordinary motion, preflight, and playback. The ordinary path keeps the coordinator
through executor submission; the playback path keeps it through its runner claim; and
preflight cannot claim `PREFLIGHTING` while either owner is active. Play also rechecks
the exact cached object identity and preflight generation after each asynchronous
boundary and after the playback service claim. A superseded or evicted prepared object
therefore cannot execute, even if a caller captured it before awaiting repository or
admission work.

The coordinator also owns a lifecycle epoch/count fence. A request captured before Stop,
Disconnect, or Shutdown cannot publish or claim afterward, while a request that starts
during the transition is rejected immediately. Playback Stop delegates runner join,
state-sink flush, and terminal publication to one shielded completion task. Canceling a
caller does not cancel that cleanup; repeated Stop calls join it until `STOPPED` releases
the motion slot.

Once preflight has published `PREFLIGHTING`, every lifecycle epoch rejection first calls
the same idempotent Stop path. A mid-claim Stop therefore cannot be overwritten by a
generic preflight-failure transition to `FAULTED`.

The same post-await rule applies to ordinary executor claim: lifecycle invalidation
cancels the exact submitted command before the caller can receive acceptance. Global
Stop runs under one shielded completion owner, so cancellation of the initiating caller
cannot truncate registered Stop hooks; repeated Stop calls join it.

Library Motion create/update/duplicate/delete operations share a process-local mutation
lock with execution validation. Validation holds an exact revision lease across the
repository read, gateway awaits, and `PLAYING` claim. This supplies one linearization
point: an earlier mutation rejects stale execution, while a later mutation cannot alter
the already immutable prepared plan.

## Alternatives

- Compile again on Play: rejected because the executed samples would not be the samples
  whose digest and violations the operator reviewed.
- Interpolate Cartesian endpoints in Joint space: rejected because it is not a TCP
  straight-line trajectory and can hide unreachable intermediate poses.
- Stream user-supplied samples over HTTP or WebSocket: rejected because it bypasses the
  Motion entity, compiler, budgets, and safety evidence.
- Use relative sleeps and replay every late sample: rejected because work time and
  pause/resume would accumulate drift or create unsafe bursts.
- Reuse the Legacy sequence player: rejected because it couples files, controller calls,
  raw state, wall time, ordered arrays, and Real behavior behind mutable flags.

## Consequences

Preflight, preview, and playback share one reviewable trajectory identity. Stale plans
fail closed and Stop remains observable and prioritized. Deterministic sampling costs
memory proportional to the bounded sample count, and Cartesian compilation costs one IK
solve per intermediate sample. The current implementation is a local single-process
Dry Run engine; it does not authorize Real motion, prove physical dynamics, or replace
Stage 8 field acceptance.
