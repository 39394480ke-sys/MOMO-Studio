# ADR 0015: Multi-factor Real-hardware authorization

- Status: Accepted as the Stage 8 foundation; session transport and global-acceptance
  details are superseded by ADR 0018 and ADR 0019.
- Date: 2026-08-24

Historical note: the invariant multi-factor/fail-closed boundary remains. Current
operation has three immutable purposes, staged capability evidence, and an HttpOnly
operator cookie; the raw-token-in-frontend and single passed-acceptance sentences below
are retained only to show the original decision.

## Context

Stage 8 needs a software path for future physical hardware without allowing a mode flag,
UI click, committed example, or optional SDK import to create authority. Real actions
have persistent physical consequences and software Stop may not establish physical safety.

## Decision

Use one deny-by-default authorization matrix. A Real adapter can be created only when
all of the following remain true at the time of use: Real control mode, Full hardware
policy, real-motion and startup flags, exact ignored local opt-in, verified non-template
Profile, complete non-template matching Calibration, verified matching Kinematics,
passed field acceptance, explicit serial/protocol/ordered Servo IDs, and an unexpired
context-bound Operator Session.

The Operator Session is single-owner, short lived, stored only as a digest/evidence in
backend memory, returned once as a raw token, and held only in frontend memory. It needs
exact typed confirmation plus physical E-stop acknowledgement. Restart, expiry,
disconnect, connection failure, token mismatch, or identity/context drift invalidates
authorization. LAN authentication is an additional independent layer.

The `ServoBus` port exposes only open/close, explicit-ID ping, bounded typed diagnostic
reads, mapped goal writes, and Stop/Hold. It exposes no scan or arbitrary register API.
Optional SDK import is lazy and occurs only inside a factory holding a complete grant;
adapter construction does not open a device. Connection pings only configured IDs and
never homes, moves, changes mode, or enables torque.

Real capabilities are separate. Provisional Kinematics blocks Cartesian, Cartesian
Playback, and Vision Follow even if Joint motion could later qualify. Every motion uses
the already-reviewed safety/prepared-trajectory entry; routes never import a Servo SDK.
Stop returns a typed physical-confidence outcome. Unverified adapter semantics return
`SAFETY_STATE_UNCERTAIN` and instruct use of the physical E-stop.

## Consequences

- Committed defaults and examples cannot authorize Real access.
- More configuration cannot weaken another missing gate; there is no debug bypass.
- Tests use Fake Bus and token-free internal evidence; autonomous verification performs
  no serial/camera operation.
- Field teams must establish SDK provenance, mappings, physical Stop, and each capability
  before changing ignored local acceptance to Passed.
- A field failure remains visible and requires a new authorization rather than automatic
  retry/reconnect.
