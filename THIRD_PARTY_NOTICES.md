# Third-party notices and provenance ledger

This file is a provenance and permission ledger, not a software license. MOMO Studio has not selected a repository license. Nothing here grants rights beyond an applicable upstream license or the explicit rights-holder authorization recorded below.

## MOMO Studio dependencies

MOMO Studio resolves its development/runtime packages through the manifests and lockfiles in this repository. They are not vendored here. Before distribution, generate and review a version-pinned dependency/license report from those lockfiles and include every required license and attribution notice.

| Ecosystem | Packages presently declared or used | Current use | Provenance action before distribution |
|---|---|---|---|
| Python | Hatchling, FastAPI, Pydantic, pydantic-settings, PyYAML, Uvicorn, NumPy and jsonschema; development tools include httpx, pytest, Ruff, mypy, types-PyYAML and types-jsonschema | Build backend, API shell, configuration, domain and persisted JSON Schema validation, mesh-free numerical kinematics and quality checks | Use the exact resolved versions in `backend/uv.lock`; collect each distribution's license metadata and bundled license text. |
| JavaScript/TypeScript | React, React DOM, React Router, Lucide React (ISC), Three.js `0.171.0` (MIT), and `urdf-loader` `0.13.1` (Apache-2.0); Vite plus TypeScript, Vitest, Testing Library, ESLint and related development tools | Web application, routing, interface icons, read-only URDF/STL visualization, tests, lint/type/build tooling | These packages are npm dependencies resolved by `frontend/package-lock.json`, not vendored source. Use the exact resolved versions in that lockfile and collect the applicable license texts and notices before distribution. |

Package names are identifiers for attribution and dependency review; they do not imply endorsement.

### V1 and V2 read-only 3D viewer assets

On 2026-08-28, the user directly stated that they created and own all MOMO V1 and V2
robot-model assets and authorized their use in MOMO Studio. This ledger records that
rights-holder assertion as the permission basis for the model assets. It does not infer
MIT, Apache-2.0, a public-domain dedication, or any other named license or terms not
stated by the user.

The V2 viewer files were copied byte-for-byte from the user-supplied archive
`MOMO-V2-3D-Viewer-ChatGPT-2026-08-28.zip`, SHA-256
`577a57c56b0f2ec0af7c486e4437fae9aeda7e8183b11aeebb2dec9c4029bf76`.
The archive identifies read-only Legacy Source commit
`ff8bbda0c2222cb57951c7913f7f12f5777b98fa` as its source.

| V2 repository file | SHA-256 |
|---|---|
| `frontend/src/assets/robot-v2/urdf/v2/soarmoce_urdf.urdf` | `0b510fc1c06a0c286fedf068da9dca96065d66afb6611bd585a3e416686eccc6` |
| `frontend/src/assets/robot-v2/meshes/v2/base_link.stl` | `8de59b1b2fa2207dcaa1427bf9ba5dcead9fcfc8d1ed520808fa6e2d6d482e67` |
| `frontend/src/assets/robot-v2/meshes/v2/Link_2.stl` | `5ac523cd4723055d38320b83c2a70b72b8233cafd141f97ad0cf1109fe4f3e17` |
| `frontend/src/assets/robot-v2/meshes/v2/Link_3.stl` | `fc2f2cea3ff5f1449a9d5c495eaccdb2cce86b0d276790a255a753ba712099dd` |
| `frontend/src/assets/robot-v2/meshes/v2/Link_4.stl` | `7c3252133180f772479de3af81b7b027877bdc87ee2e1c51ac160f6f217c5c62` |
| `frontend/src/assets/robot-v2/meshes/v2/Link_5.stl` | `375155bf0f47ff4f0a363709cc841f971d0611c04a6101ce8c68934211ba9526` |
| `frontend/src/assets/robot-v2/meshes/v2/Link_6.stl` | `4046d2513ee572b286ac226d1297aac9ca5d150e3c0718674403b7b089bfe996` |
| `frontend/src/assets/robot-v2/meshes/v2/Link_7.stl` | `a75abef799eec297d9d9bde8b81b9aec006060f594a7b5a4fcfb339b6d2447cc` |

The seven V1 STL files were copied byte-for-byte from the same read-only Legacy commit.
The Legacy V1 URDF's SHA-256 is
`5a8d3f6cc39e095537f73aca5562b5f79d625c0bcf80c753800f5a67228b0edf`.
Its viewer derivative preserves the authored mesh, link, origin, and J11-J15 joint data,
but changes the Legacy prismatic `J10` base edge into fixed joint `V1_BASE_FIXED` and removes
its axis/limit. That explicit adaptation makes the visualization's movable-joint contract
match MOMO Studio V1: exactly J11-J15 and no movable J10 rail axis. It deliberately retains
the user's authored static `base_link` mesh and is not evidence of a measured rail-less
physical exterior. The derivative URDF SHA-256 is
`cea16e30b2a698e32ef4a0a968c50004a53497276c5797312b9d732b661c1aa0`.

| V1 repository file | SHA-256 |
|---|---|
| `frontend/src/assets/robot-v1/urdf/v1/soarmoce_urdf.urdf` | `cea16e30b2a698e32ef4a0a968c50004a53497276c5797312b9d732b661c1aa0` |
| `frontend/src/assets/robot-v1/meshes/v1/base_link.stl` | `26873eb3e28a18b1fd2fdd111475e0a8c3dd843a52b935fba746ae32f3370be4` |
| `frontend/src/assets/robot-v1/meshes/v1/Link_1.stl` | `1b7dbfd8407bc9eb1f636f955701240b481afb200f02135684a695cd2e7088c0` |
| `frontend/src/assets/robot-v1/meshes/v1/Link_2.stl` | `7e9a1721ef0248e6ebabd274135491bcef292414fcde52398fe7db7e7b39450e` |
| `frontend/src/assets/robot-v1/meshes/v1/Link_3.stl` | `1dfa561185bb49d238cf71f53c723e2ae9e226f25247e3c427861528ed7b8a80` |
| `frontend/src/assets/robot-v1/meshes/v1/Link_4.stl` | `c719094564620b0b3d8c09bb360763209b626bcdde07472fb3581456c5cc2f99` |
| `frontend/src/assets/robot-v1/meshes/v1/Link_5.stl` | `4a875bf77cc71866d23ad13e24ce5d1865d97cfc951a622f8f6898ae53fcc67b` |
| `frontend/src/assets/robot-v1/meshes/v1/Link_6.stl` | `7c6d45ffafe235ba5b5853e5917fd9e9ca77700fb0092ad12ecb715e64ef8114` |

The source archive and Legacy root contain no separate named license or copyright notice
for these files. The user's direct ownership and authorization statement above supplies
the permission relied on by MOMO Studio, so the previous unknown-rights blocker for these
robot-model assets is removed. Repository-wide licensing, dependency notices, and rights
for unrelated Legacy material remain separate matters. Model inclusion is not evidence of
technical accuracy, safety, calibration, collision, reachability, TCP, or real-motion
validation.

The viewer uses Three.js `0.171.0` under MIT and `urdf-loader` `0.13.1` under
Apache-2.0 as npm dependencies; no library source from the archive's `vendor/` directory
was copied. Exact upstream texts are retained as
`THIRD_PARTY_LICENSES/three-0.171.0-MIT.txt` and
`THIRD_PARTY_LICENSES/urdf-loader-0.13.1-Apache-2.0.txt`. The Three.js text is
byte-for-byte the `LICENSE` shipped in the locked npm package and matches upstream tag
`r171`. The `urdf-loader` npm package identifies Apache-2.0 but its published `files`
allowlist omits the repository license file; the retained text is therefore copied from
the exact upstream `v0.13.1` tag, including its California Institute of Technology
copyright notice. The direct rights-holder authorization for the MOMO meshes above is
independent of those library licenses and does not label the meshes MIT or Apache-2.0.

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

### Optional read-only OpenCV camera provider

The `camera` extra declares and locks `opencv-python-headless>=4.10,<5`; the current lock
selects `opencv-python-headless 4.14.0.94`. Installed package metadata reports Apache
2.0 and the canonical `opencv/opencv-python` project. Distribution review must also
collect the wheel's license files and bundled native/transitive notices. The default
`make install` does not install this extra. Normal Synthetic composition does not import
OpenCV. Even in an authorized live composition, startup does not import OpenCV or open a
device; a confirmed operator request is required.

The capability ledger mentions an optional OpenCV live tracker, built-in HOG person
detector, and Haar-based face detector. All are unavailable in the Stage 7 composition.
No executable detector/tracker implementation, HOG people-detector coefficients, Haar
cascade file, model weight, binary, or external asset was copied, vendored, installed,
or downloaded by this Stage. A capability name is not a provenance or redistribution
approval.

Before distributing OpenCV or activating later tracking/detection providers, record and
review:

1. the exact selected package, version/build, canonical source, license files, bundled
   third-party notices, native/transitive components, and platform wheels;
2. the exact tracker algorithm/module and any patent or build-configuration constraints;
3. the origin, author/copyright, license, version, and checksum of the HOG default people
   detector data/implementation used by the selected build;
4. the exact Haar cascade filename/path, original upstream source, author/copyright,
   license, version, checksum, attribution, and redistribution terms; and
5. camera/device behavior and field verification separate from software licensing.

The available Synthetic person/face detectors and tracker are MOMO Studio deterministic
scene fixtures written for repository tests and browser acceptance. They contain no
third-party weights or training data and must not be represented as a general-purpose
learned model.

### Optional read-only Feetech adapter

The optional `hardware` extra pins `ftservo-python-sdk==2.0.0`, published from the
official `ftservo/FTServo_Python` project. The reviewed wheel is
`ftservo_python_sdk-2.0.0-py3-none-any.whl`, SHA-256
`c8303df01b2c772f3e1dffbb3b789e2d39545f6fb187ec45032c7737356be2a4`. Its bundled
`LICENSE` grants the MIT License and its package metadata identifies the official GitHub
repository. The wheel depends on `pyserial`.

MOMO Studio's independently written bridge imports this optional SDK only after a valid
read-only operator grant. It opens one explicitly configured port at 1 Mbps and exposes
only explicit-ID ping, model validation, operating-mode/limit reads, present-position
reads, and torque-state reads. It contains no enumeration or scan call and all
goal/torque/arbitrary-register writes remain unavailable. The default install and default
composition do not install/import the package or open a serial device.

Physical Stop/Hold and every motion/write path remain unverified and disabled. The bus
still reports `SAFETY_STATE_UNCERTAIN` for Stop rather than guessing. Distribution review
must collect the SDK and pyserial license files/notices for the selected platform and
repeat vulnerability review. Read-only field acceptance is separate from permission to
calibrate or move the robot.

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

The audited Legacy root has no `LICENSE` or `COPYING` file. Its own `THIRD_PARTY_NOTICES.md` identifies some third-party material but does not grant a license for the repository as a whole. As recorded above, the V1/V2 viewer assets were copied or explicitly adapted for this implementation, with the user's later direct ownership and authorization statement as the permission basis. The earlier unknown-rights model-asset blocker is removed, but this does not license the Legacy repository as a whole. Any unrelated Legacy code or asset still requires its own provenance and rights review before inclusion.

## Legacy third-party candidates and characterization status

| Candidate in Legacy commit | Legacy evidence | Inclusion status | Required action |
|---|---|---|---|
| SOARM MOCE-derived hardware conventions and compatibility facts, including joint naming, servo-ID/multi-turn conventions, selected scales and calibration-field concepts | Legacy `THIRD_PARTY_NOTICES.md:5-15` identifies these as third-party-related material. | Not copied; facts were used only to identify items requiring verification. | Trace each fact to an original source and determine whether it is an uncopyrightable fact, licensed documentation, or implementation detail. Record author, URL/version and license before reuse. Independently verify safety-critical values against the actual hardware. |
| V1/V2 `soarmoce_urdf.urdf` files and versioned STL meshes | Legacy notices characterized the files as third-party and did not state terms; the user's later direct statement identifies the user as creator/rightsholder and authorizes their use in MOMO Studio. | Stage 3 independently transcribed numerical facts into provisional mesh-free models. The frontend now contains both model variants as itemized above. V2 remains byte-identical; V1 meshes remain byte-identical and its URDF is explicitly adapted to fix the obsolete J10 base edge. The model-asset rights blocker is removed by the recorded authorization. | Retain commit/archive/file hashes and the user authorization record. Independently verify geometry, axes, limits, frames and TCP. The Legacy V1 rail mismatch remains a technical fact addressed only for visualization by the documented fixed-joint derivative. |
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

For an asset without an applicable upstream license or an explicit rights-holder authorization such as the one recorded above, unverified provenance remains a release blocker and is not permission to label the asset as MOMO Studio-original.
