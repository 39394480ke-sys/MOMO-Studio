# Third-party notices and provenance ledger

This file is a provenance ledger, not a software license. MOMO Studio has not selected a repository license. Nothing here grants rights beyond the applicable upstream license.

## MOMO Studio dependencies

MOMO Studio resolves its development/runtime packages through the manifests and lockfiles in this repository. They are not vendored here. Before distribution, generate and review a version-pinned dependency/license report from those lockfiles and include every required license and attribution notice.

| Ecosystem | Packages presently declared or used | Current use | Provenance action before distribution |
|---|---|---|---|
| Python | Hatchling, FastAPI, Pydantic, pydantic-settings, PyYAML, Uvicorn, NumPy and jsonschema; development tools include httpx, pytest, Ruff, mypy, types-PyYAML and types-jsonschema | Build backend, API shell, configuration, domain and persisted JSON Schema validation, mesh-free numerical kinematics and quality checks | Use the exact resolved versions in `backend/uv.lock`; collect each distribution's license metadata and bundled license text. |
| JavaScript/TypeScript | React, React DOM, React Router, and Lucide React (ISC); Vite plus TypeScript, Vitest, Testing Library, ESLint and related development tools | Web application, routing, interface icons, tests, lint/type/build tooling | Use the exact resolved versions in the frontend lockfile; collect package license metadata and required notices. |

Package names are identifiers for attribution and dependency review; they do not imply endorsement.

### Stage 3 numerical dependency

NumPy is used only for deterministic, mesh-free serial-chain FK and damped-least-squares
IK. It is installed from PyPI through `backend/uv.lock`, not vendored or copied into this
repository. The lock currently resolves NumPy `2.4.6` for Python below 3.12 and `2.5.2`
for Python 3.12 and newer. In the current Python 3.11 verification environment, installed
NumPy `2.4.6` distribution metadata identifies the aggregate license expression as
`BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`. That observation does not verify
the metadata or bundled license files of the Python 3.12+ `2.5.2` wheel. Downstream
distribution must inspect and include the exact license files shipped by every selected
wheel rather than treating this ledger as a substitute. Canonical project source:
<https://numpy.org/>.

Stage 3 verification exported the locked runtime requirements and ran `pip-audit`; it
reported no known vulnerabilities. The audit tool warned while normalizing one invalid
legacy package-metadata version specifier, but completed successfully. The frontend
production audit (`npm audit --omit=dev --audit-level=moderate`) reported zero
vulnerabilities. These point-in-time results do not replace release-time vulnerability
and license review.

### Stage 4 persisted-schema dependency

Stage 4 adds `jsonschema` so each stored Pose/Motion document is checked against the
same generated Draft 2020-12 schema used as the public artifact before Pydantic domain
construction. The packages are installed from PyPI through `backend/uv.lock`, not
vendored into this repository. The current lock and installed Python 3.11 metadata show:

| Package | Locked version | Purpose | Installed metadata license expression |
|---|---:|---|---|
| `jsonschema` | `4.26.0` | Runtime Draft 2020-12 validation | `MIT` |
| `attrs` | `26.1.0` | `jsonschema`/`referencing` runtime dependency | `MIT` |
| `jsonschema-specifications` | `2025.9.1` | Referenced JSON Schema vocabularies | `MIT` |
| `referencing` | `0.37.0` | JSON reference registry/resolution | `MIT` |
| `rpds-py` | `2026.6.3` | Persistent data structures used by `referencing` | `MIT` |
| `types-jsonschema` | `4.26.0.20260518` | Development-only mypy stubs | `Apache-2.0` |

`referencing` also uses the already locked `typing-extensions` on supported Python
versions. Version and license strings above are a point-in-time metadata observation,
not a substitute for collecting and reviewing the actual license files of every wheel
selected for distribution. The Stage 4 lock check passed with 44 resolved packages; its
locked-runtime `pip-audit` reported no known vulnerabilities, and the frontend production
audit reported zero vulnerabilities. These checks do not replace distribution-time
license-file collection or vulnerability review.

## Project-generated design reference

`docs/design/stage-01-shell-concept.png` was generated specifically for this repository on 2026-08-23 with OpenAI's built-in image-generation tool from a MOMO Studio Stage 1 UI brief. It used no Legacy image, robot asset, logo, screenshot or other third-party reference input. The file is design evidence only and is not rendered by the product.

## Read-only Legacy source

MOMO Studio Stage 1 audited the following repository as a read-only Legacy Source:

- Source: `https://github.com/39394480ke-sys/MOMO_RobotARM.git`
- Branch: `V2`
- Commit: `ff8bbda0c2222cb57951c7913f7f12f5777b98fa`

No Legacy source file, recorded motion, calibration value, runtime data, model weight,
URDF, mesh or other binary asset was copied into MOMO Studio during Stage 1. The audit
produced only independently written migration/provenance documentation. Stage 3 later
transcribed numerical joint-axis and origin-transform facts into independently written,
mesh-free provisional models; it still copied no Legacy URDF, STL, mesh, controller code,
or binary asset. For Stage 4, the main task inspected only pinned tracked Git objects via
`git show`: V1/V2 sample action JSON shapes, their README, and relevant
action-library/recorder/common-alias source text. The independently written importer and
synthetic fixtures copy no tracked sample numeric motion/raw values, Legacy source
implementation, ignored/local data, Calibration, runtime record, code, or asset.

The audited Legacy root has no `LICENSE` or `COPYING` file. Its own `THIRD_PARTY_NOTICES.md` identifies some third-party material but does not grant a license for the repository as a whole. Therefore no Legacy code or asset may be copied, modified or redistributed until its copyright holder, original source and applicable license are established.

## Legacy third-party candidates and characterization status

| Candidate in Legacy commit | Legacy evidence | Inclusion status | Required action |
|---|---|---|---|
| SOARM MOCE-derived hardware conventions and compatibility facts, including joint naming, servo-ID/multi-turn conventions, selected scales and calibration-field concepts | Legacy `THIRD_PARTY_NOTICES.md:5-15` identifies these as third-party-related material. | Not copied; facts were used only to identify items requiring verification. | Trace each fact to an original source and determine whether it is an uncopyrightable fact, licensed documentation, or implementation detail. Record author, URL/version and license before reuse. Independently verify safety-critical values against the actual hardware. |
| V1/V2 `soarmoce_urdf.urdf` files and versioned STL meshes | Legacy `THIRD_PARTY_NOTICES.md:11-15` and `URDF运动学仿真/README_URDF运动学仿真.md:14-41` state that the URDF/STL files are third-party and their license/attribution/redistribution terms still require review. | No URDF, STL, mesh, controller code, or binary asset is included. Stage 3 independently transcribed numerical joint-axis and origin-transform facts into provisional mesh-free models for Dry Run characterization. | Identify the original model release, copyright holder and exact license; determine the provenance and distribution obligations of the transcribed numerical facts; preserve required attribution. Independently verify model geometry, axes, limits and TCP. V1 is additionally blocked because the Legacy V1 URDF contains a rail contrary to the product contract. |
| `face_detection_yunet_2023mar.onnx` | Legacy vision code calls it an OpenCV YuNet model (`视觉识别与跟随/vision/人脸检测_face_detector.py:1,20-22`), but the Legacy notice contains no source or license entry. | Not included. | Identify the exact upstream model/version, model-card or repository, training/data/license terms, checksum and attribution requirements before adding any weight. |
| `gesture_recognizer.task` | Legacy code uses it with optional MediaPipe gesture recognition (`视觉识别与跟随/vision/手势识别_gesture_detector.py:20-23,76-100`), but the Legacy notice contains no source or license entry. | Not included; gesture recognition is retired from the first MOMO Studio product version. | Do not migrate. If scope changes in a later approved product decision, restart provenance/license/model-data review from the original upstream source. |

## Data deliberately excluded

The following are not third-party dependencies and must not be treated as reusable source assets:

- serial-port or device-specific local overrides;
- real calibration and calibration backups;
- raw present-position or multi-turn runtime state tied to a physical device;
- logs, `.env` files, secrets, API keys or machine-local paths;
- user poses, recorded motions, photos, videos or camera captures;
- Legacy runtime/community content.

The audited Legacy Git index contains a calibration backup artifact despite ignore rules. Its contents were not inspected and it was not copied. Future migration tooling must exclude such paths by default.

## Contribution and release rule

For every future third-party code or asset addition, update this ledger in the same change with:

1. exact artifact/file names and checksums where applicable;
2. original project, author/copyright holder and canonical source URL;
3. exact version, tag or commit;
4. license name/version and a copy or required link/text;
5. required attribution, notice, modification and redistribution conditions;
6. whether the artifact is modified and how;
7. a safety/technical verification record for hardware, robot-model or ML assets.

Unverified provenance is a release blocker, not permission to label an asset as MOMO Studio-original.
