"""Fake-only product lifecycle safety cleanup regression tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest

from momo.application.services.device_diagnostics_service import DeviceDiagnosticsService
from momo.application.services.motion_service import MotionApplicationService
from momo.application.services.operator_session_service import OperatorSessionTokenError
from momo.application.services.product_lifecycle_service import ProductLifecycleService
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.enums import (
    CalibrationStatus,
    ControlMode,
    HardwareAccessPolicy,
    ProfileVerificationStatus,
    RobotConnectionState,
    RobotVariant,
)
from momo.domain.real_hardware import OperatorSessionEvidence
from momo.domain.runtime import RobotStatus
from momo.ports.servo_bus import ServoBus


def _status() -> RobotStatus:
    return RobotStatus(
        robot_id="primary",
        variant=RobotVariant.V2,
        control_mode=ControlMode.REAL,
        hardware_access_policy=HardwareAccessPolicy.FULL,
        connection_state=RobotConnectionState.DISCONNECTED,
        connected=False,
        profile_fingerprint="a" * 64,
        profile_verification_status=ProfileVerificationStatus.VERIFIED_FOR_REAL,
        calibration_status=CalibrationStatus.READY_FOR_REAL,
        positions={"j11": 0.0},
        units={"j11": "deg"},
    )


class _Robot:
    settings = SimpleNamespace(control_mode=ControlMode.REAL)

    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def connect(self) -> RobotStatus:
        self.events.append("robot-connect")
        return _status()


class _Motion:
    def __init__(self, events: list[str], *, fail_disconnect: bool = False) -> None:
        self.events = events
        self.fail_disconnect = fail_disconnect

    async def disconnect(self) -> RobotStatus:
        self.events.append("motion-disconnect")
        if self.fail_disconnect:
            raise RuntimeError("synthetic motion cleanup failure")
        return _status()


class _Device:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.cleanup_hook: object | None = None
        self.bus = cast(ServoBus, object())
        self.evidence = cast(
            OperatorSessionEvidence,
            SimpleNamespace(session_id="session", scopes=frozenset()),
        )

    def bind_product_cleanup(self, hook: object) -> None:
        self.cleanup_hook = hook

    async def connect_for_product_session(
        self,
        token: str,
    ) -> tuple[ServoBus, OperatorSessionEvidence, object]:
        self.events.append(f"device-session-connect:{token}")
        return self.bus, self.evidence, object()

    async def disconnect(self, token: str) -> None:
        self.events.append(f"device-auth-disconnect:{token}")
        raise OperatorSessionTokenError("Operator session token is invalid")

    async def disconnect_trusted(self) -> None:
        self.events.append("device-trusted-disconnect")


def _lifecycle(
    events: list[str],
    *,
    fail_motion_disconnect: bool = False,
) -> tuple[ProductLifecycleService, _Device, list[OperatorSessionEvidence]]:
    device = _Device(events)
    bound: list[OperatorSessionEvidence] = []

    def bind(bus: ServoBus, evidence: OperatorSessionEvidence) -> None:
        assert bus is device.bus
        bound.append(evidence)
        events.append("bind-session-evidence")

    def unbind() -> None:
        events.append("unbind")

    lifecycle = ProductLifecycleService(
        robot=cast(RobotApplicationService, _Robot(events)),
        motion=cast(
            MotionApplicationService,
            _Motion(events, fail_disconnect=fail_motion_disconnect),
        ),
        device=cast(DeviceDiagnosticsService, device),
        bind_real_bus=bind,
        unbind_real_bus=unbind,
    )
    return lifecycle, device, bound


def test_real_connect_binds_complete_session_evidence_not_a_joint_bootstrap() -> None:
    async def scenario() -> None:
        events: list[str] = []
        lifecycle, device, bound = _lifecycle(events)

        await lifecycle.connect("opaque-token")

        assert bound == [device.evidence]
        assert events == [
            "device-session-connect:opaque-token",
            "bind-session-evidence",
            "robot-connect",
        ]

    asyncio.run(scenario())


def test_invalid_disconnect_token_still_revokes_binding() -> None:
    async def scenario() -> None:
        events: list[str] = []
        lifecycle, _, _ = _lifecycle(events)

        with pytest.raises(OperatorSessionTokenError, match="invalid"):
            await lifecycle.disconnect("expired-token")

        assert events == [
            "motion-disconnect",
            "device-auth-disconnect:expired-token",
            "unbind",
        ]

    asyncio.run(scenario())


def test_trusted_cleanup_closes_device_even_when_motion_cleanup_fails() -> None:
    async def scenario() -> None:
        events: list[str] = []
        lifecycle, _, _ = _lifecycle(events, fail_motion_disconnect=True)

        with pytest.raises(RuntimeError, match="synthetic motion cleanup failure"):
            await lifecycle.trusted_cleanup()

        assert events == [
            "motion-disconnect",
            "device-trusted-disconnect",
            "unbind",
        ]

    asyncio.run(scenario())
