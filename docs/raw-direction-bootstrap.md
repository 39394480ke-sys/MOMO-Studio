# Raw ± direction bootstrap

Status: software chain implemented and hardware-disabled. No physical Raw writer is
composed by the release bootstrap, and the tracked/default switch is false.

This workflow removes the Calibration bootstrap deadlock for one identified robot unit.
It is narrower than the normal Commissioning Motion Test: it has no logical `mm`/`deg`
target, no arbitrary Servo/register endpoint, and no production-motion authority.

## Candidate data and current-unit data

The V2 candidate is derived from read-only Legacy source
`MOMO_RobotARM@ff8bbda0c2222cb57951c7913f7f12f5777b98fa`:

- enabled joints J10–J15 and Servo IDs 10–15;
- STS3215 / Feetech SCS protocol facts and 4096 counts/revolution;
- Profile direction/scale candidates, phase candidate `28`, and candidate Raw bounds;
- the existing V2 URDF and Kinematics provenance.

Those values remain candidates. The workflow never imports Legacy runtime positions,
device-local Calibration, serial ports, or multi-turn runtime state. The current unit's
Raw zero is read fresh only after the operator confirms that the current physical pose
matches the URDF zero pose.

## One-session field flow

1. The operator obtains one `RAW_DIRECTION_TEST` session by confirming the physical
   E-stop, clear workspace, and current-pose/URDF-zero match.
2. The backend reads every Profile-enabled explicit Servo ID and captures one immutable,
   session-only Raw-zero snapshot.
3. The session lasts at most 300 seconds and allows at most 24 commands.
4. Each button press arms one named Profile joint. The backend prepares exactly one
   `Raw +8` or `Raw −8` count command and rejects a target outside ±32 counts from the
   captured zero.
5. Release/cancel requests Stop/Hold. A 400 ms backend deadman independently expires the
   active attempt.
6. Both Raw signs must be observed for a joint before the operator can answer whether
   physical motion agrees with the Legacy/Profile-to-URDF direction candidate.
7. After every enabled joint has both signs plus one explicit observation, the backend
   generates a session-only Calibration draft. One exact final confirmation marks the
   draft reviewed; it still is not persisted or promoted to real Calibration.

## Capability boundary

The browser supplies only a Profile joint ID, `RAW_PLUS`/`RAW_MINUS`, and explicit human
observations. It never supplies a raw target, Servo ID, speed, register, adapter, file
path, direction sign, zero, phase, or bound. The backend owns all targets and hard caps.

The dedicated bus port permits only: read one allowlisted present position, write one
backend-prepared command, Stop/Hold that Servo, session reset, and close. It cannot Home,
Jog, Playback, Follow, change torque/mode, scan, enumerate, or access arbitrary registers.
`RAW_DIRECTION_TEST` sessions cannot be reused or upgraded for read-only commissioning,
normal commissioning motion, or production motion.

## Current verification limit

Automated acceptance uses only an opt-in in-memory Fake Raw bus. It verifies the fixed
step, one-Servo allowlist, zero envelope, command cap, deadman, both-sign requirement,
draft derivation, final confirmation, and late-pointer-release frontend fence. It does
not validate STS3215 writes, physical Stop/Hold, E-stop behavior, direction, zero,
backlash, current, heat, collision clearance, or limits. A reviewed physical adapter and
separate on-site authorization are required before any real movement.
