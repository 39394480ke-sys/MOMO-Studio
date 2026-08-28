"""Unit isolation for the reviewed STS3215 bridge; no serial device is opened."""

from __future__ import annotations

from types import ModuleType

import pytest

from momo.adapters.hardware.feetech_servo_bus import FeetechAdapterPendingError
from momo.adapters.hardware.ftservo_read_only_bridge import (
    BAUD_RATE,
    STS3215_MODEL_NUMBER,
    FtServoReadOnlyBridge,
)


class FakePort:
    def __init__(self, device: str, events: list[tuple[str, object]]) -> None:
        self.device = device
        self.events = events

    def setBaudRate(self, baudrate: int) -> bool:
        self.events.append(("set-baud", (self.device, baudrate)))
        return True

    def closePort(self) -> None:
        self.events.append(("close", self.device))


class FakePacket:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events
        self.mode = 0
        self.minimum = 0
        self.maximum = 0
        self.torque = 0

    def ping(self, servo_id: int) -> tuple[int, int, int]:
        self.events.append(("ping", servo_id))
        return STS3215_MODEL_NUMBER, 0, 0

    def ReadPos(self, servo_id: int) -> tuple[int, int, int]:
        self.events.append(("position", servo_id))
        return -123, 0, 0

    def read1ByteTxRx(self, servo_id: int, address: int) -> tuple[int, int, int]:
        self.events.append(("read1", (servo_id, address)))
        return ({33: self.mode, 40: self.torque}[address], 0, 0)

    def read2ByteTxRx(self, servo_id: int, address: int) -> tuple[int, int, int]:
        self.events.append(("read2", (servo_id, address)))
        return ({9: self.minimum, 11: self.maximum}[address], 0, 0)


def fake_sdk(
    events: list[tuple[str, object]],
    packet: FakePacket,
) -> ModuleType:
    module = ModuleType("scservo_sdk")

    def port_handler(device: str) -> FakePort:
        events.append(("port", device))
        return FakePort(device, events)

    def sms_sts(port: FakePort) -> FakePacket:
        events.append(("packet", port.device))
        return packet

    module.PortHandler = port_handler  # type: ignore[attr-defined]
    module.sms_sts = sms_sts  # type: ignore[attr-defined]
    return module


def test_bridge_is_inert_until_exact_open_and_exposes_only_reads() -> None:
    events: list[tuple[str, object]] = []
    packet = FakePacket(events)
    module = fake_sdk(events, packet)
    imports: list[str] = []

    def importer(name: str) -> ModuleType:
        imports.append(name)
        return module

    bridge = FtServoReadOnlyBridge(importer=importer)
    assert imports == []
    assert events == []

    with pytest.raises(ValueError, match="only STS3215"):
        bridge.open("/dev/explicit", "OTHER")
    assert imports == []
    assert events == []

    bridge.open("/dev/explicit", "STS3215")
    assert imports == ["scservo_sdk"]
    assert events == [
        ("port", "/dev/explicit"),
        ("packet", "/dev/explicit"),
        ("set-baud", ("/dev/explicit", BAUD_RATE)),
    ]
    assert bridge.ping(10) is True
    assert bridge.read_present_position(10) == -123
    assert bridge.read_operating_mode(10) == "MULTI_TURN"
    assert bridge.read_torque_state(10) is False

    packet.maximum = 4095
    assert bridge.read_operating_mode(10) == "SINGLE_TURN"
    packet.mode = 1
    assert bridge.read_operating_mode(10) == "VELOCITY_CLOSED_LOOP"

    with pytest.raises(FeetechAdapterPendingError, match="read-only"):
        bridge.write_goal_positions({10: 100})
    assert not any(event[0].startswith("write") for event in events)
    bridge.close()
    assert events[-1] == ("close", "/dev/explicit")


def test_bridge_fails_closed_on_wrong_model_or_servo_status() -> None:
    events: list[tuple[str, object]] = []
    packet = FakePacket(events)
    module = fake_sdk(events, packet)
    bridge = FtServoReadOnlyBridge(importer=lambda _: module)
    bridge.open("/dev/explicit", "STS3215")

    packet.ping = lambda servo_id: (999, 0, 0)  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="not reviewed STS3215"):
        bridge.ping(10)

    packet.ping = lambda servo_id: (STS3215_MODEL_NUMBER, -6, 0)  # type: ignore[method-assign]
    assert bridge.ping(10) is False

    packet.ReadPos = lambda servo_id: (0, 0, 4)  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="status error"):
        bridge.read_present_position(10)


def test_bridge_type_surface_has_no_general_register_or_torque_write() -> None:
    bridge = FtServoReadOnlyBridge()
    assert not hasattr(bridge, "scan")
    assert not hasattr(bridge, "read_register")
    assert not hasattr(bridge, "write_register")
    assert not hasattr(bridge, "enable_torque")
