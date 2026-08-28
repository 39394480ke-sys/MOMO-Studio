# Legacy pose import

MOMO Studio provides an offline, explicit-source importer for old named-pose library
JSON. It is dry-run by default, does not discover Legacy installations, and never
connects to robot hardware.

The old pose format sometimes omits both the hardware variant and `joint_order`.
Because a six-value array is not enough evidence to infer a robot contract, the
operator must select `V1` or `V2` explicitly. The selected profile supplies missing
metadata; every such use is recorded as a warning. A pose explicitly tagged as the
other variant is skipped.

From the repository root:

```bash
PYTHONPATH=backend/src backend/.venv/bin/python -m momo.tools.import_legacy_poses \
  --source /explicit/path/to/pose-library.json \
  --variant V2 \
  --dry-run
```

Review the JSON report, especially `SKIPPED_VARIANT` and `QUARANTINED` entries. Write
only after the selection and warnings are accepted:

```bash
PYTHONPATH=backend/src backend/.venv/bin/python -m momo.tools.import_legacy_poses \
  --source /explicit/path/to/pose-library.json \
  --variant V2 \
  --write
```

Each accepted pose receives a fresh UUID filename. The importer preserves joint
targets in product units (`mm` for V2 `j10`, `deg` for revolute joints), validates the
current profile limits, and recomputes TCP with the current kinematics model. It stores
only the source basename and SHA-256 digest as provenance; absolute source paths are
not persisted.

Legacy gripper, raw/multi-turn, TCP, hardware, calibration, and serial data are not
imported. Imported snapshots have no live observation sequence or hardware snapshot.
Out-of-limit or ambiguous entries remain quarantined rather than being clamped or
silently reinterpreted.
