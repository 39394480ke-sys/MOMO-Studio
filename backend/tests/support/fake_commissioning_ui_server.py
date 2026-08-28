#!/usr/bin/env python3
"""Localhost-only Fake API for the Settings commissioning browser E2E.

This deliberately lives under ``backend/tests/support`` and imports no MOMO
hardware, camera, serial, or production-bootstrap code.  It simulates only the
HTTP contracts needed by the V2 Settings commissioning flow.  Its JSON state is
explicitly marked fake and is useful for proving that all twelve joint-direction
results and the joint-acceptance decision survive a frontend reload.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import uuid
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

HOST: Final = "127.0.0.1"
JOINTS: Final = ("j10", "j11", "j12", "j13", "j14", "j15")
UNITS: Final = {"j10": "mm", **{joint_id: "deg" for joint_id in JOINTS[1:]}}
PROFILE_FINGERPRINT: Final = "a" * 64
CALIBRATION_FINGERPRINT: Final = "b" * 64
KINEMATICS_FINGERPRINT: Final = "c" * 64
DEVICE_FINGERPRINT: Final = "d" * 64
ROBOT_UNIT_ID: Final = "MOMO-V2-FAKE-E2E-001"
CHECKLIST_VERSION: Final = "field-v2"
SOFTWARE_COMMIT: Final = "eb90d516dcc1cb7c09d75fc7c5894e9f619116a6"
READ_ONLY_CONFIRMATION: Final = "I CONFIRM THE PHYSICAL E-STOP IS READY"
MOTION_TEST_CONFIRMATION: Final = "I CONFIRM THE WORKSPACE IS CLEAR FOR SINGLE-JOINT TESTS"
REAL_MOTION_CONFIRMATION: Final = "I CONFIRM REAL MOTION PREREQUISITES"


def now() -> datetime:
    return datetime.now(UTC)


def timestamp(value: datetime | None = None) -> str:
    return (value or now()).isoformat().replace("+00:00", "Z")


def stable_uuid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"momo-studio-fake-ui:{name}"))


def joint_definition(joint_id: str) -> dict[str, Any]:
    unit = UNITS[joint_id]
    return {
        "joint_id": joint_id,
        "joint_type": "PRISMATIC" if unit == "mm" else "REVOLUTE",
        "domain_unit": unit,
        "minimum": 0 if unit == "mm" else -180,
        "maximum": 500 if unit == "mm" else 180,
        "home": 0,
        "servo_id": 10 + JOINTS.index(joint_id),
        "motor_degrees_per_domain_unit": 1.0,
        "raw_counts_per_motor_revolution": 4096,
        "direction": 1,
        "operating_mode": "MULTI_TURN",
        "home_present_raw": 2048,
        "raw_bounds": [0, 4095],
        "raw_reachable": True,
    }


class HarnessState:
    """Thread-safe fake evidence state; sessions and watchdogs remain ephemeral."""

    def __init__(self, state_file: Path) -> None:
        self.state_file = state_file
        self.lock = threading.RLock()
        self.persisted = self._load()
        self.operator_session: dict[str, Any] | None = None
        self.commissioning_session_id: str | None = None
        self.commissioning_state = "IDLE"
        self.active_joint_id: str | None = None
        self.command_count = 0
        self.last_evidence_id: str | None = None

    @staticmethod
    def empty() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "fake_only": True,
            "robot_unit_id": ROBOT_UNIT_ID,
            "diagnostics_complete": False,
            "pre_motion_checks_complete": False,
            "joint_evidence": {},
            "joint_motion_accepted": False,
            "field_acceptance_evidence_id": None,
            "updated_at": timestamp(),
        }

    def _load(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return self.empty()
        try:
            value = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self.empty()
        if not isinstance(value, dict) or value.get("fake_only") is not True:
            return self.empty()
        clean = self.empty()
        clean["diagnostics_complete"] = value.get("diagnostics_complete") is True
        clean["pre_motion_checks_complete"] = value.get("pre_motion_checks_complete") is True
        clean["joint_motion_accepted"] = value.get("joint_motion_accepted") is True
        clean["field_acceptance_evidence_id"] = value.get("field_acceptance_evidence_id")
        raw_evidence = value.get("joint_evidence")
        if isinstance(raw_evidence, dict):
            clean["joint_evidence"] = {
                joint_id: {
                    direction: evidence
                    for direction, evidence in directions.items()
                    if direction in {"POSITIVE", "NEGATIVE"} and isinstance(evidence, dict)
                }
                for joint_id, directions in raw_evidence.items()
                if joint_id in JOINTS and isinstance(directions, dict)
            }
        return clean

    def save(self) -> None:
        self.persisted["updated_at"] = timestamp()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            dir=self.state_file.parent,
            prefix=f".{self.state_file.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.persisted, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, self.state_file)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @property
    def connected(self) -> bool:
        # Connection is intentionally process-local, never persisted as evidence.
        return getattr(self, "_connected", False)

    @connected.setter
    def connected(self, value: bool) -> None:
        self._connected = value

    def evidence_for(self, joint_id: str, direction: str) -> dict[str, Any] | None:
        directions = self.persisted["joint_evidence"].get(joint_id, {})
        value = directions.get(direction)
        return value if isinstance(value, dict) else None

    def selected_evidence_ids(self) -> list[str]:
        selected: list[str] = []
        for joint_id in JOINTS:
            for direction in ("POSITIVE", "NEGATIVE"):
                evidence = self.evidence_for(joint_id, direction)
                if evidence is not None:
                    selected.append(str(evidence["id"]))
        return selected

    def all_joint_directions_complete(self) -> bool:
        return len(self.selected_evidence_ids()) == len(JOINTS) * 2


class FakeCommissioningHandler(BaseHTTPRequestHandler):
    server: FakeCommissioningServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        # One compact record is easier to audit than BaseHTTPRequestHandler prose.
        print(
            json.dumps(
                {"fake_api": True, "client": self.client_address[0], "message": format % args}
            )
        )

    def _json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 32_768:
            raise ValueError("request body exceeds fake harness limit")
        if length == 0:
            return {}
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _send(
        self,
        payload: Any,
        status: HTTPStatus = HTTPStatus.OK,
        *,
        cookie: str | None = None,
    ) -> None:
        encoded = (
            b""
            if status is HTTPStatus.NO_CONTENT
            else json.dumps(payload, separators=(",", ":")).encode()
        )
        self.send_response(status)
        if encoded:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-MOMO-Fake-Harness", "true")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if encoded:
            self.wfile.write(encoded)

    def _error(self, status: HTTPStatus, code: str, message: str) -> None:
        self._send(
            {"code": code, "message": message, "details": {"fake_only": True}},
            status,
        )

    def _route(self) -> str:
        path = urlsplit(self.path).path
        prefix = "/api/v1"
        return path[len(prefix) :] if path.startswith(prefix) else path

    def do_GET(self) -> None:
        route = self._route()
        state = self.server.state
        with state.lock:
            if route == "/health":
                self._send(
                    {
                        "status": "ok",
                        "product": "MOMO Studio",
                        "version": "0.1.0-rc1",
                        "stage": 8,
                        "control_mode": "REAL",
                        "hardware_access_policy": "FULL",
                        "real_motion_enabled": False,
                    }
                )
            elif route == "/meta":
                self._send(self._meta())
            elif route == "/robot":
                self._send(self._robot())
            elif route == "/robot/profile":
                self._send(self._profile())
            elif route == "/calibration/status":
                self._send(self._calibration_status())
            elif route == "/robot/diagnostics":
                self._send(self._runtime_diagnostics())
            elif route == "/device/readiness":
                self._send(self._readiness())
            elif route == "/device/field-acceptance":
                self._send(self._field_acceptance_status())
            elif route == "/device/field-acceptance/progress":
                self._send(self._field_progress())
            elif route == "/device/commissioning/status":
                self._send(self._commissioning_status())
            elif route == "/kinematics-verification":
                self._send(
                    {"state": "MISSING", "stale_fields": [], "evidence_id": None, "point_count": 0}
                )
            elif route == "/__fake__/state":
                self._send(
                    {
                        **state.persisted,
                        "connected_process_local": state.connected,
                        "active_operator_purpose": (state.operator_session or {}).get("purpose"),
                    }
                )
            else:
                self._error(HTTPStatus.NOT_FOUND, "FAKE_ROUTE_NOT_IMPLEMENTED", route)

    def do_POST(self) -> None:
        route = self._route()
        state = self.server.state
        try:
            body = self._json_body()
        except (ValueError, json.JSONDecodeError) as error:
            self._error(HTTPStatus.BAD_REQUEST, "INVALID_FAKE_REQUEST", str(error))
            return
        with state.lock:
            if route == "/device/operator-session":
                self._create_operator_session(body)
            elif route == "/device/connect":
                if not self._require_purpose("COMMISSIONING_READ_ONLY"):
                    return
                state.connected = True
                self._send({"diagnostics": self._device_diagnostics()})
            elif route == "/device/disconnect":
                if not self._require_purpose("COMMISSIONING_READ_ONLY"):
                    return
                state.connected = False
                self._send({"diagnostics": self._device_diagnostics()})
            elif route == "/device/diagnostics":
                if not self._require_purpose("COMMISSIONING_READ_ONLY") or not state.connected:
                    if state.connected is False:
                        self._error(
                            HTTPStatus.CONFLICT, "FAKE_DEVICE_DISCONNECTED", "Connect first"
                        )
                    return
                state.persisted["diagnostics_complete"] = True
                state.save()
                self._send(self._device_diagnostics())
            elif route == "/device/field-acceptance/pre-motion-checks":
                self._complete_pre_motion(body)
            elif route == "/device/field-acceptance/joint-motion":
                self._accept_joint_motion(body)
            elif route == "/device/commissioning/session":
                self._start_commissioning_session()
            elif route.startswith("/device/commissioning/joints/") and route.endswith("/arm"):
                joint_id = route.split("/")[4]
                self._arm_joint(joint_id)
            elif route.startswith("/device/commissioning/joints/") and route.endswith(
                "/tests/start"
            ):
                joint_id = route.split("/")[4]
                self._run_joint_test(joint_id, body)
            elif route == "/device/commissioning/tests/heartbeat":
                if not self._require_commissioning_runtime():
                    return
                self._send(self._commissioning_status(deadman=True))
            elif route == "/device/commissioning/tests/stop":
                if not self._require_purpose("COMMISSIONING_MOTION_TEST"):
                    return
                state.active_joint_id = None
                if state.commissioning_session_id is not None:
                    state.commissioning_state = "COMPLETED"
                self._send(self._commissioning_status())
            else:
                self._error(HTTPStatus.NOT_FOUND, "FAKE_ROUTE_NOT_IMPLEMENTED", route)

    def do_DELETE(self) -> None:
        route = self._route()
        state = self.server.state
        with state.lock:
            if route != "/device/operator-session":
                self._error(HTTPStatus.NOT_FOUND, "FAKE_ROUTE_NOT_IMPLEMENTED", route)
                return
            state.operator_session = None
            state.commissioning_session_id = None
            state.commissioning_state = "IDLE"
            state.active_joint_id = None
            self._send(
                {},
                HTTPStatus.NO_CONTENT,
                cookie="momo_operator_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0",
            )

    def _meta(self) -> dict[str, Any]:
        return {
            "product": "MOMO Studio",
            "version": "0.1.0-rc1",
            "api_version": "v1",
            "stage": 8,
            "active_robot_variant": "V2",
            "supported_robot_variants": ["V1", "V2"],
            "supported_control_modes": ["DRY_RUN", "REAL"],
            "active_control_mode": "REAL",
            "hardware_access_policy": "FULL",
            "real_motion_enabled": False,
            "release_status": "FIELD_ACCEPTANCE_REQUIRED",
            "dry_run_validated": True,
            "real_hardware_field_acceptance": "PENDING",
        }

    def _robot(self) -> dict[str, Any]:
        state = self.server.state
        return {
            "robot_id": "primary",
            "variant": "V2",
            # The product runtime remains isolated even though Settings displays
            # the Real commissioning boundary.
            "control_mode": "DRY_RUN",
            "hardware_access_policy": "DISABLED",
            "connection_state": "DISCONNECTED",
            "connected": False,
            "profile_fingerprint": PROFILE_FINGERPRINT,
            "profile_verification_status": "VERIFIED_FOR_REAL",
            "calibration_status": "READY_FOR_REAL",
            "positions": {joint_id: 0 for joint_id in JOINTS},
            "units": UNITS,
            "raw_positions": None,
            "last_error": None,
            "updated_at": timestamp(),
            "state_sequence": state.command_count,
            "hardware_accessed": False,
            "stale": False,
        }

    def _profile(self) -> dict[str, Any]:
        return {
            "profile": {
                "schema_version": "1.0.0",
                "variant": "V2",
                "display_name": "MOMO V2 Fake Commissioning E2E",
                "has_linear_rail": True,
                "enabled_joints": list(JOINTS),
                "joint_definitions": [joint_definition(joint_id) for joint_id in JOINTS],
                "urdf_reference": None,
                "tcp_link": "tool0",
                "template": False,
                "verification_status": "VERIFIED_FOR_REAL",
                "source": "backend/tests/support/fake_commissioning_ui_server.py",
                "source_revision": "fake-e2e-v1",
                "description": "Fake-only V2 browser commissioning fixture.",
            },
            "fingerprint": PROFILE_FINGERPRINT,
            "kinematics_fingerprint": KINEMATICS_FINGERPRINT,
            "real_eligible": True,
        }

    def _calibration_status(self) -> dict[str, Any]:
        return {
            "status": "READY_FOR_REAL",
            "configured": True,
            "template": False,
            "variant_match": True,
            "profile_match": True,
            "joint_set_match": True,
            "mapping_match": True,
            "complete": True,
            "calibration_valid": True,
            "real_readiness": "FIELD_ACCEPTANCE_PENDING",
            "blocking_reasons": ["Physical Field Acceptance remains pending"],
        }

    def _runtime_diagnostics(self) -> dict[str, Any]:
        return {
            "hardware_access_policy": "DISABLED",
            "runtime_state_path": "FAKE_ONLY_NO_RUNTIME_FILE",
            "runtime_state_valid": True,
            "runtime_state_diagnostic": "Fake browser harness; no hardware runtime",
            "quarantined_runtime_file": None,
            "backend_version": "0.1.0-rc1",
            "legacy_source_commit": "ff8bbda0c2222cb57951c7913f7f12f5777b98fa",
            "stage_policy": "FAKE_BROWSER_COMMISSIONING_ONLY",
            "active_profile_fingerprint": PROFILE_FINGERPRINT,
            "active_kinematics_fingerprint": KINEMATICS_FINGERPRINT,
            "hardware_accessed": False,
        }

    def _confirmation(self, purpose: str) -> dict[str, Any]:
        required_text = {
            "COMMISSIONING_READ_ONLY": READ_ONLY_CONFIRMATION,
            "COMMISSIONING_MOTION_TEST": MOTION_TEST_CONFIRMATION,
            "REAL_MOTION": REAL_MOTION_CONFIRMATION,
        }[purpose]
        return {
            "robot_id": "primary",
            "robot_unit_id": ROBOT_UNIT_ID,
            "variant": "V2",
            "profile_fingerprint": PROFILE_FINGERPRINT,
            "calibration_fingerprint": CALIBRATION_FINGERPRINT,
            "kinematics_fingerprint": KINEMATICS_FINGERPRINT,
            "masked_serial_port": "FAKE://NO-SERIAL",
            "masked_servo_ids": [f"FAKE-{joint_id.upper()}" for joint_id in JOINTS],
            "protocol": "FAKE_ONLY",
            "session_purpose": purpose,
            "field_acceptance_evidence_id": self.server.state.persisted[
                "field_acceptance_evidence_id"
            ],
            "physical_estop_required": True,
            "workspace_clear_required": purpose == "COMMISSIONING_MOTION_TEST",
            "required_confirmation_text": required_text,
        }

    def _detail(
        self,
        *,
        ready: bool,
        authorized: bool = False,
        reason: str,
        evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "ready": ready,
            "authorized": authorized,
            "blocked_reasons": [] if authorized else [reason],
            "required_evidence": [] if authorized else (evidence or []),
        }

    def _readiness(self) -> dict[str, Any]:
        state = self.server.state
        session = state.operator_session
        purpose = (session or {}).get("purpose")
        no_session = session is None
        pre_motion = state.persisted["pre_motion_checks_complete"] is True
        joint_accepted = state.persisted["joint_motion_accepted"] is True
        read_only_authorizable = no_session
        motion_test_authorizable = no_session and pre_motion and not joint_accepted
        details = {
            "commissioning_read_only": self._detail(
                ready=True,
                authorized=purpose == "COMMISSIONING_READ_ONLY",
                reason="COMMISSIONING_READ_ONLY_SESSION_REQUIRED",
            ),
            "commissioning_motion_test": self._detail(
                ready=pre_motion,
                authorized=purpose == "COMMISSIONING_MOTION_TEST",
                reason="COMMISSIONING_MOTION_SESSION_REQUIRED"
                if pre_motion
                else "PRE_MOTION_CHECKS_REQUIRED",
                evidence=[] if pre_motion else ["PRE_MOTION_CHECKS"],
            ),
            "real_joint_motion": self._detail(
                ready=False,
                reason="REAL_MOTION_REMAINS_FIELD_GATED",
                evidence=["JOINT_MOTION_ACCEPTANCE"]
                if not joint_accepted
                else ["KINEMATICS_FIELD_EVIDENCE"],
            ),
            "real_cartesian_motion": self._detail(
                ready=False,
                reason="KINEMATICS_FIELD_EVIDENCE_REQUIRED",
                evidence=["KINEMATICS_FIELD_EVIDENCE"],
            ),
            "real_playback": self._detail(
                ready=False,
                reason="PLAYBACK_FIELD_ACCEPTANCE_REQUIRED",
                evidence=["PLAYBACK_FIELD_ACCEPTANCE"],
            ),
            "real_vision_follow": self._detail(
                ready=False,
                reason="VISION_FOLLOW_FIELD_ACCEPTANCE_REQUIRED",
                evidence=["VISION_FOLLOW_FIELD_ACCEPTANCE"],
            ),
        }
        return {
            "state": "OPERATOR_SESSION_ACTIVE" if session else "COMMISSIONING_READY",
            "ready": False,
            "session_authorizable": read_only_authorizable or motion_test_authorizable,
            "commissioning_session_authorizable": read_only_authorizable,
            "commissioning_motion_session_authorizable": motion_test_authorizable,
            "motion_session_authorizable": False,
            "blocking_reasons": ["REAL_MOTION_REMAINS_FIELD_GATED"],
            "capabilities": {
                "commissioning_diagnostics_ready": True,
                "calibration_capture_ready": True,
                "commissioning_motion_test_ready": pre_motion,
                "real_joint_motion_ready": False,
                "real_cartesian_motion_ready": False,
                "real_playback_ready": False,
                "real_vision_follow_ready": False,
            },
            "capability_details": details,
            "authorization_options": [
                {
                    "purpose": option_purpose,
                    "authorizable": {
                        "COMMISSIONING_READ_ONLY": read_only_authorizable,
                        "COMMISSIONING_MOTION_TEST": motion_test_authorizable,
                        "REAL_MOTION": False,
                    }[option_purpose],
                    "confirmation": self._confirmation(option_purpose),
                }
                for option_purpose in (
                    "COMMISSIONING_READ_ONLY",
                    "COMMISSIONING_MOTION_TEST",
                    "REAL_MOTION",
                )
            ],
            "confirmation": self._confirmation("COMMISSIONING_READ_ONLY"),
            "session": None
            if session is None
            else {
                "active": True,
                "session_id": session["session_id"],
                "expires_at": session["expires_at"],
                "purpose": session["purpose"],
                "scopes": session["scopes"],
            },
            "calibration_configured": True,
            "connected": state.connected,
        }

    def _field_acceptance_status(self) -> dict[str, Any]:
        state = self.server.state
        has_record = state.persisted["pre_motion_checks_complete"] is True
        return {
            "state": "VALID" if has_record else "MISSING",
            "effective_status": "PENDING",
            "checklist_version": CHECKLIST_VERSION,
            "stale_fields": [],
            "evidence_id": state.persisted["field_acceptance_evidence_id"],
            "accepted_at": state.persisted["updated_at"] if has_record else None,
            "accepted_by": "fake-browser-operator" if has_record else None,
            "required_confirmation_text": "FAKE HARNESS DOES NOT CONSTITUTE FIELD ACCEPTANCE",
        }

    def _field_progress(self) -> dict[str, Any]:
        state = self.server.state
        selected_ids = state.selected_evidence_ids()
        complete = state.all_joint_directions_complete()
        pre_motion = state.persisted["pre_motion_checks_complete"] is True
        accepted = state.persisted["joint_motion_accepted"] is True
        if accepted:
            progress_state = "KINEMATICS_VERIFICATION_PENDING"
        elif selected_ids:
            progress_state = "JOINT_MOTION_TESTING"
        elif pre_motion:
            progress_state = "PRE_MOTION_CHECKS_COMPLETE"
        elif state.persisted["diagnostics_complete"]:
            progress_state = "READ_ONLY_COMMISSIONING_COMPLETE"
        else:
            progress_state = "CALIBRATION_COMPLETE"
        capabilities = ["PRE_MOTION_CHECKS"] if pre_motion else []
        if accepted:
            capabilities.append("JOINT_MOTION")
        joints = []
        for joint_id in JOINTS:
            positive = state.evidence_for(joint_id, "POSITIVE")
            negative = state.evidence_for(joint_id, "NEGATIVE")
            joints.append(
                {
                    "joint_id": joint_id,
                    "unit": UNITS[joint_id],
                    "positive_evidence_id": None if positive is None else positive["id"],
                    "negative_evidence_id": None if negative is None else negative["id"],
                    "complete": positive is not None and negative is not None,
                }
            )
        return {
            "state": progress_state,
            "robot_unit_id": ROBOT_UNIT_ID,
            "checklist_version": CHECKLIST_VERSION,
            "valid_capabilities": capabilities,
            "pre_motion_checks_complete": pre_motion,
            "joint_motion_tests_complete": complete,
            "joint_motion_accepted": accepted,
            "ready_to_accept_joint_motion": pre_motion and complete and not accepted,
            "completed_joint_directions": len(selected_ids),
            "required_joint_directions": len(JOINTS) * 2,
            "joints": joints,
            "selected_test_evidence_ids": selected_ids,
            "rejected_test_evidence_ids": [],
            "stale_field_acceptance_evidence_ids": [],
            "legacy_field_acceptance_evidence_ids": [],
            "physical_stop_verification": "PENDING",
            "full_acceptance_complete": False,
        }

    def _device_diagnostics(self) -> dict[str, Any]:
        state = self.server.state
        return {
            "connected": state.connected,
            "captured_at": timestamp(),
            "dependency": {
                "adapter_id": "fake-commissioning-ui",
                "state": "AVAILABLE",
                "package_name": None,
                "license_status": "TEST_ONLY",
                "notice": "Fake adapter; no serial or camera access exists.",
            },
            "hardware_policy": "FULL",
            "masked_serial_port": "FAKE://NO-SERIAL",
            "masked_servo_ids": [f"FAKE-{joint_id.upper()}" for joint_id in JOINTS],
            "protocol": "FAKE_ONLY",
            "profile": {
                "configured": True,
                "fingerprint": PROFILE_FINGERPRINT,
                "verification_status": "VERIFIED_FOR_REAL",
                "template": False,
                "ready_for_real": True,
            },
            "calibration": {
                "configured": True,
                "fingerprint": CALIBRATION_FINGERPRINT,
                "verification_status": "FAKE_E2E_ONLY",
                "template": False,
                "ready_for_real": True,
            },
            "kinematics": {
                "configured": True,
                "fingerprint": KINEMATICS_FINGERPRINT,
                "verification_status": "FIELD_VERIFICATION_REQUIRED",
                "template": False,
                "ready_for_real": False,
            },
            "field_acceptance": "PENDING",
            "readiness": "FAKE_COMMISSIONING_ONLY",
            "records": [
                {
                    "joint_id": joint_id,
                    "masked_servo_id": f"FAKE-{joint_id.upper()}",
                    "ping_responded": True,
                    "operating_mode": "FAKE_BOUNDED",
                    "present_raw": 2048,
                    "logical_value": 0,
                    "raw_bounds": [0, 4095],
                    "torque_enabled": False,
                }
                for joint_id in JOINTS
            ],
            "last_error": None,
        }

    def _commissioning_status(self, *, deadman: bool = False) -> dict[str, Any]:
        state = self.server.state
        return {
            "state": state.commissioning_state,
            "session_id": state.commissioning_session_id,
            "active_joint_id": state.active_joint_id,
            "command_count": state.command_count,
            "session_expires_at": None
            if state.commissioning_session_id is None
            else timestamp(now() + timedelta(minutes=5)),
            "deadman_expires_at": timestamp(now() + timedelta(milliseconds=500))
            if deadman or state.commissioning_state in {"ARMED", "MOVING"}
            else None,
            "last_evidence_id": state.last_evidence_id,
            "failure_reason": None,
            "physical_stop_verification": "PENDING",
        }

    def _require_purpose(self, purpose: str) -> bool:
        session = self.server.state.operator_session
        if session is not None and session.get("purpose") == purpose:
            return True
        self._error(
            HTTPStatus.FORBIDDEN,
            "FAKE_OPERATOR_SESSION_REQUIRED",
            f"A {purpose} session is required",
        )
        return False

    def _require_commissioning_runtime(self) -> bool:
        state = self.server.state
        if not self._require_purpose("COMMISSIONING_MOTION_TEST"):
            return False
        if state.commissioning_session_id is None:
            self._error(
                HTTPStatus.CONFLICT,
                "FAKE_COMMISSIONING_SESSION_REQUIRED",
                "Bind the test session first",
            )
            return False
        return True

    def _create_operator_session(self, body: dict[str, Any]) -> None:
        state = self.server.state
        if state.operator_session is not None:
            self._error(
                HTTPStatus.CONFLICT, "FAKE_SESSION_ALREADY_ACTIVE", "End the current session first"
            )
            return
        purpose = body.get("purpose")
        allowed = {
            "COMMISSIONING_READ_ONLY": True,
            "COMMISSIONING_MOTION_TEST": state.persisted["pre_motion_checks_complete"] is True
            and not state.persisted["joint_motion_accepted"],
            "REAL_MOTION": False,
        }
        if purpose not in allowed or not allowed[purpose]:
            self._error(HTTPStatus.FORBIDDEN, "FAKE_PURPOSE_NOT_AUTHORIZABLE", str(purpose))
            return
        confirmation = self._confirmation(str(purpose))
        if body.get("confirmation_text") != confirmation["required_confirmation_text"]:
            self._error(
                HTTPStatus.UNPROCESSABLE_ENTITY, "FAKE_CONFIRMATION_MISMATCH", "Exact text required"
            )
            return
        if body.get("physical_estop_confirmed") is not True:
            self._error(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "FAKE_ESTOP_CONFIRMATION_REQUIRED",
                "Confirmation required",
            )
            return
        if (
            confirmation["workspace_clear_required"]
            and body.get("workspace_clear_confirmed") is not True
        ):
            self._error(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "FAKE_WORKSPACE_CONFIRMATION_REQUIRED",
                "Confirmation required",
            )
            return
        scopes = {
            "COMMISSIONING_READ_ONLY": ["DIAGNOSTICS_READ", "CALIBRATION_CAPTURE"],
            "COMMISSIONING_MOTION_TEST": ["COMMISSIONING_SINGLE_JOINT_TEST"],
        }[str(purpose)]
        session_id = str(uuid.uuid4())
        issued_at = now()
        state.operator_session = {
            "session_id": session_id,
            "issued_at": timestamp(issued_at),
            "expires_at": timestamp(issued_at + timedelta(minutes=10)),
            "purpose": purpose,
            "scopes": scopes,
            "evidence": confirmation,
        }
        self._send(
            state.operator_session,
            cookie=(
                f"momo_operator_session={session_id}; Path=/; HttpOnly; "
                "SameSite=Strict; Max-Age=600"
            ),
        )

    def _complete_pre_motion(self, body: dict[str, Any]) -> None:
        state = self.server.state
        if not self._require_purpose("COMMISSIONING_READ_ONLY"):
            return
        if not state.connected or not state.persisted["diagnostics_complete"]:
            self._error(
                HTTPStatus.CONFLICT, "FAKE_FRESH_DIAGNOSTICS_REQUIRED", "Run diagnostics first"
            )
            return
        if body.get("checklist_version") != CHECKLIST_VERSION:
            self._error(HTTPStatus.CONFLICT, "FAKE_CHECKLIST_MISMATCH", CHECKLIST_VERSION)
            return
        state.persisted["pre_motion_checks_complete"] = True
        state.persisted["field_acceptance_evidence_id"] = stable_uuid("pre-motion")
        state.save()
        self._send(self._field_progress())

    def _start_commissioning_session(self) -> None:
        state = self.server.state
        if not self._require_purpose("COMMISSIONING_MOTION_TEST"):
            return
        if not state.persisted["pre_motion_checks_complete"]:
            self._error(HTTPStatus.CONFLICT, "FAKE_PRE_MOTION_REQUIRED", "Record pre-motion checks")
            return
        if state.commissioning_session_id is None:
            state.commissioning_session_id = str(uuid.uuid4())
            state.commissioning_state = "AUTHORIZED"
            state.active_joint_id = None
        self._send(self._commissioning_status())

    def _arm_joint(self, joint_id: str) -> None:
        state = self.server.state
        if not self._require_commissioning_runtime():
            return
        if joint_id not in JOINTS:
            self._error(HTTPStatus.NOT_FOUND, "FAKE_JOINT_NOT_ENABLED", joint_id)
            return
        if state.commissioning_state not in {"AUTHORIZED", "COMPLETED", "FAILED"}:
            self._error(HTTPStatus.CONFLICT, "FAKE_TEST_BUSY", state.commissioning_state)
            return
        state.active_joint_id = joint_id
        state.commissioning_state = "ARMED"
        self._send(self._commissioning_status(deadman=True))

    def _run_joint_test(self, joint_id: str, body: dict[str, Any]) -> None:
        state = self.server.state
        if not self._require_commissioning_runtime():
            return
        if (
            joint_id not in JOINTS
            or state.active_joint_id != joint_id
            or state.commissioning_state != "ARMED"
        ):
            self._error(HTTPStatus.CONFLICT, "FAKE_JOINT_NOT_ARMED", joint_id)
            return
        delta = body.get("signed_delta")
        speed = body.get("requested_speed")
        acceleration = body.get("requested_acceleration")
        duration = body.get("command_duration_s")
        if not isinstance(delta, (int, float)) or delta == 0:
            self._error(
                HTTPStatus.UNPROCESSABLE_ENTITY, "FAKE_DELTA_INVALID", "Non-zero delta required"
            )
            return
        cap = 1 if UNITS[joint_id] == "mm" else 2
        if abs(float(delta)) > cap or not isinstance(speed, (int, float)) or float(speed) <= 0:
            self._error(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "FAKE_ENVELOPE_REJECTED",
                "Bounded request required",
            )
            return
        if (
            not isinstance(acceleration, (int, float))
            or float(acceleration) <= 0
            or not isinstance(duration, (int, float))
            or float(duration) > 1
        ):
            self._error(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "FAKE_ENVELOPE_REJECTED",
                "Bounded request required",
            )
            return
        direction = "POSITIVE" if float(delta) > 0 else "NEGATIVE"
        evidence_id = stable_uuid(f"{joint_id}:{direction}:{state.command_count + 1}")
        raw_delta = round(float(delta) * 10)
        observed = timestamp()
        evidence = {
            "schema_version": 1,
            "revision": 1,
            "id": evidence_id,
            "robot_unit_id": ROBOT_UNIT_ID,
            "robot_variant": "V2",
            "profile_fingerprint": PROFILE_FINGERPRINT,
            "calibration_fingerprint": CALIBRATION_FINGERPRINT,
            "device_fingerprint": DEVICE_FINGERPRINT,
            "joint_id": joint_id,
            "unit": UNITS[joint_id],
            "start_value": 0,
            "requested_delta": float(delta),
            "target_value": float(delta),
            "final_value": float(delta),
            "start_raw": 2048,
            "final_raw": 2048 + raw_delta,
            "requested_speed": float(speed),
            "measured_or_observed_result": "Fake bounded readback matched; no hardware accessed.",
            "direction_expected": direction,
            "direction_observed": direction,
            "divergence": 0,
            "stop_behavior": "PHYSICAL_BEHAVIOR_PENDING",
            "started_at": observed,
            "completed_at": observed,
            "software_commit": SOFTWARE_COMMIT,
            "operator_id": "fake-browser-operator",
            "request_id": str(body.get("request_id") or stable_uuid(f"request:{evidence_id}")),
            "session_id": state.commissioning_session_id,
            "prepared_target_raw": 2048 + raw_delta,
            "result": "PASSED",
            "failure_reason_optional": None,
        }
        state.persisted["joint_evidence"].setdefault(joint_id, {})[direction] = evidence
        state.command_count += 1
        state.last_evidence_id = evidence_id
        state.active_joint_id = None
        state.commissioning_state = "COMPLETED"
        state.save()
        self._send(evidence)

    def _accept_joint_motion(self, body: dict[str, Any]) -> None:
        state = self.server.state
        if not self._require_purpose("COMMISSIONING_MOTION_TEST"):
            return
        if body.get("checklist_version") != CHECKLIST_VERSION:
            self._error(HTTPStatus.CONFLICT, "FAKE_CHECKLIST_MISMATCH", CHECKLIST_VERSION)
            return
        if (
            not state.persisted["pre_motion_checks_complete"]
            or not state.all_joint_directions_complete()
        ):
            self._error(
                HTTPStatus.CONFLICT, "FAKE_ALL_DIRECTIONS_REQUIRED", "Complete all 12 directions"
            )
            return
        state.persisted["joint_motion_accepted"] = True
        state.persisted["field_acceptance_evidence_id"] = stable_uuid("joint-motion-accepted")
        state.save()
        self._send(self._field_progress())


class FakeCommissioningServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, state: HarnessState) -> None:
        super().__init__((HOST, port), FakeCommissioningHandler)
        self.state = state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path(tempfile.gettempdir()) / "momo-studio-fake-commissioning-ui-state.json",
    )
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Reset only the explicitly selected fake state file before serving.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("--port must be between 1024 and 65535")
    state_file = args.state_file.expanduser().resolve()
    if args.reset_state and state_file.exists():
        state_file.unlink()
    state = HarnessState(state_file)
    server = FakeCommissioningServer(args.port, state)
    print(
        json.dumps(
            {
                "fake_commissioning_ui_server": "ready",
                "url": f"http://{HOST}:{args.port}",
                "state_file": str(state_file),
                "hardware_access": False,
                "camera_access": False,
            }
        ),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
