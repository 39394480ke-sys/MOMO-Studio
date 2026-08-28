"""Dry Run lifecycle serialization and runtime persistence safety tests."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from momo.adapters.hardware.dry_run_robot_driver import DryRunRobotDriver
from momo.adapters.storage.file_calibration_repository import FileCalibrationRepository
from momo.adapters.storage.profile_repository import FileProfileRepository
from momo.adapters.storage.runtime_state_repository import FileRuntimeStateRepository
from momo.adapters.time.system_clock import SystemClock
from momo.application.services.calibration_service import CalibrationService
from momo.application.services.profile_service import ProfileService
from momo.application.services.robot_service import DriverFactory, RobotApplicationService
from momo.domain.enums import RobotConnectionState, RobotVariant, StopResult
from momo.domain.errors import (
    RobotAlreadyConnectedError,
    RobotApplicationError,
    VariantSwitchWhileConnectedError,
)
from momo.domain.robot import RobotId, RobotProfile
from momo.domain.runtime import RuntimeState
from momo.ports.robot_driver import RobotDriver
from momo.settings import Settings, repository_root


def dry_run_factory(
    robot_id: RobotId,
    profile: RobotProfile,
    positions: dict[str, float] | None,
) -> RobotDriver:
    return DryRunRobotDriver(robot_id, profile, positions)


def make_service(
    runtime_directory: Path,
    *,
    variant: RobotVariant = RobotVariant.V2,
    driver_factory: DriverFactory = dry_run_factory,
) -> RobotApplicationService:
    root = repository_root()
    return RobotApplicationService(
        Settings(active_robot_variant=variant),
        ProfileService(FileProfileRepository(root / "robot_profiles")),
        CalibrationService(FileCalibrationRepository(root / "calibration" / "examples")),
        FileRuntimeStateRepository(runtime_directory),
        driver_factory=driver_factory,
        clock=SystemClock(),
    )


def test_initial_state_is_disconnected_at_profile_home(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    async def scenario() -> None:
        status = await service.get_status()
        assert status.connection_state is RobotConnectionState.DISCONNECTED
        assert status.connected is False
        assert status.positions == {joint_id: 0.0 for joint_id in status.units}
        assert set(status.positions) == {"j10", "j11", "j12", "j13", "j14", "j15"}
        assert status.hardware_accessed is False

    asyncio.run(scenario())


def test_connect_disconnect_and_stop_are_safe_and_idempotent(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    async def scenario() -> None:
        initial = await service.get_status()
        stopped_disconnected = await service.stop()
        assert stopped_disconnected.result == StopResult.NOT_CONNECTED.value
        assert stopped_disconnected.status.positions == initial.positions

        connected = await service.connect()
        assert connected.connection_state is RobotConnectionState.CONNECTED
        with pytest.raises(RobotAlreadyConnectedError):
            await service.connect()

        before_stop = await service.get_status()
        stopped = await service.stop()
        assert stopped.result == StopResult.STOPPED.value
        assert stopped.status.positions == before_stop.positions

        disconnected = await service.disconnect()
        assert disconnected.connection_state is RobotConnectionState.DISCONNECTED
        repeated = await service.disconnect()
        assert repeated == disconnected
        stopped_again = await service.stop()
        assert stopped_again.result == StopResult.NOT_CONNECTED.value

    asyncio.run(scenario())


def test_variant_switch_requires_disconnected_and_replaces_joint_set(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    pre_switch_calls: list[None] = []

    async def before_switch() -> None:
        pre_switch_calls.append(None)

    async def scenario() -> None:
        v1 = await service.switch_variant(RobotVariant.V1, before_switch=before_switch)
        assert set(v1.positions) == {"j11", "j12", "j13", "j14", "j15"}
        assert "j10" not in v1.positions
        assert v1.connection_state is RobotConnectionState.DISCONNECTED
        assert pre_switch_calls == [None]

        unchanged = await service.switch_variant(RobotVariant.V1, before_switch=before_switch)
        assert unchanged == v1
        assert pre_switch_calls == [None]

        await service.connect()
        with pytest.raises(VariantSwitchWhileConnectedError):
            await service.switch_variant(RobotVariant.V2, before_switch=before_switch)
        assert pre_switch_calls == [None]
        assert (await service.get_status()).variant is RobotVariant.V1

    asyncio.run(scenario())


def test_disconnect_then_immediate_variant_switch_persists_latest_variant(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    async def scenario() -> None:
        await service.connect()
        await service.drain_runtime_persistence()
        await service.disconnect()
        switched = await service.switch_variant(RobotVariant.V1)
        await service.drain_runtime_persistence()

        persisted = service.runtime_repository.load("primary")
        assert persisted is not None
        assert persisted.variant is RobotVariant.V1
        assert persisted.state_sequence == switched.state_sequence
        assert set(persisted.positions) == {"j11", "j12", "j13", "j14", "j15"}

    asyncio.run(scenario())


def test_runtime_repository_round_trip_uses_atomic_same_directory_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FileRuntimeStateRepository(tmp_path)
    profile = FileProfileRepository(repository_root() / "robot_profiles").get(RobotVariant.V1)
    state = RuntimeState(
        robot_id="primary",
        variant=RobotVariant.V1,
        profile_fingerprint=profile.fingerprint,
        positions={joint_id: 0.0 for joint_id in profile.enabled_joints},
        units={joint_id: "deg" for joint_id in profile.enabled_joints},
        state_sequence=8,
    )
    replacements: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def observe_replace(source: str | Path, destination: str | Path) -> None:
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", observe_replace)
    repository.save(state)
    assert repository.load("primary") == state
    assert replacements
    source, destination = replacements[-1]
    assert source.parent == destination.parent == tmp_path.resolve()
    assert destination.name == "primary.json"
    assert not list(tmp_path.glob("*.tmp"))


def test_same_variant_runtime_state_is_restored_safely(tmp_path: Path) -> None:
    repository = FileRuntimeStateRepository(tmp_path)
    profile = FileProfileRepository(repository_root() / "robot_profiles").get(RobotVariant.V2)
    positions = {joint_id: 0.0 for joint_id in profile.enabled_joints}
    positions["j10"] = 12.5
    repository.save(
        RuntimeState(
            robot_id="primary",
            variant=RobotVariant.V2,
            profile_fingerprint=profile.fingerprint,
            positions=positions,
            units={item.joint_id: item.domain_unit.value for item in profile.joint_definitions},
            state_sequence=21,
        )
    )
    service = make_service(tmp_path)

    async def scenario() -> None:
        status = await service.get_status()
        assert status.positions["j10"] == 12.5
        assert status.state_sequence == 21
        assert status.connection_state is RobotConnectionState.DISCONNECTED

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mutation",
    [
        "fingerprint",
        "variant",
        "missing_joint",
        "unknown_joint",
        "wrong_unit",
        "nan",
        "boolean",
    ],
)
def test_incompatible_runtime_state_is_quarantined_and_home_is_used(
    tmp_path: Path,
    mutation: str,
) -> None:
    profile = FileProfileRepository(repository_root() / "robot_profiles").get(RobotVariant.V2)
    payload = RuntimeState(
        robot_id="primary",
        variant=RobotVariant.V2,
        profile_fingerprint=profile.fingerprint,
        positions={joint_id: 0.0 for joint_id in profile.enabled_joints},
        units={item.joint_id: item.domain_unit.value for item in profile.joint_definitions},
        state_sequence=9,
    ).model_dump(mode="json")
    if mutation == "fingerprint":
        payload["profile_fingerprint"] = "0" * 64
    elif mutation == "variant":
        payload["variant"] = "V1"
    elif mutation == "missing_joint":
        del payload["positions"]["j15"]
    elif mutation == "unknown_joint":
        payload["positions"]["j99"] = 0.0
    elif mutation == "wrong_unit":
        payload["units"]["j10"] = "deg"
    elif mutation == "nan":
        payload["positions"]["j10"] = float("nan")
    else:
        payload["positions"]["j10"] = True
    (tmp_path / "primary.json").write_text(json.dumps(payload), encoding="utf-8")

    service = make_service(tmp_path)

    async def scenario() -> None:
        status = await service.get_status()
        assert status.positions == {joint_id: 0.0 for joint_id in profile.enabled_joints}
        diagnostics = await service.diagnostics()
        assert diagnostics["runtime_state_valid"] is False
        assert diagnostics["quarantined_runtime_file"] is not None

        await service.stop()
        await service.drain_runtime_persistence()
        recovered = await service.diagnostics()
        assert recovered["runtime_state_valid"] is True

    asyncio.run(scenario())
    assert not (tmp_path / "primary.json").read_text(encoding="utf-8").startswith("nan")
    assert list(tmp_path.glob("primary.quarantine-*.json"))


@pytest.mark.parametrize("content", [b"{broken", b"\xff\xfe\x00"])
def test_corrupt_runtime_state_is_quarantined_without_crashing(
    tmp_path: Path,
    content: bytes,
) -> None:
    (tmp_path / "primary.json").write_bytes(content)
    service = make_service(tmp_path)

    async def scenario() -> None:
        status = await service.get_status()
        assert status.connection_state is RobotConnectionState.DISCONNECTED
        diagnostics = await service.diagnostics()
        assert diagnostics["runtime_state_valid"] is False
        assert diagnostics["quarantined_runtime_file"] is not None

    asyncio.run(scenario())
    assert list(tmp_path.glob("primary.quarantine-*.json"))


def test_runtime_repository_rejects_path_traversal(tmp_path: Path) -> None:
    repository = FileRuntimeStateRepository(tmp_path)
    with pytest.raises(ValueError, match="safe"):
        repository.load("../primary")


class CountingFactory:
    def __init__(self) -> None:
        self.count = 0

    def __call__(
        self,
        robot_id: RobotId,
        profile: RobotProfile,
        positions: dict[str, float] | None,
    ) -> RobotDriver:
        self.count += 1
        return DryRunRobotDriver(robot_id, profile, positions)


def test_concurrent_connect_is_serialized_and_uses_one_driver(tmp_path: Path) -> None:
    factory = CountingFactory()
    service = make_service(tmp_path, driver_factory=factory)

    async def scenario() -> None:
        results = await asyncio.gather(
            service.connect(),
            service.connect(),
            return_exceptions=True,
        )
        assert sum(isinstance(item, RobotAlreadyConnectedError) for item in results) == 1
        assert (await service.get_status()).connection_state is RobotConnectionState.CONNECTED

    asyncio.run(scenario())
    assert factory.count == 1


class SlowDryRunDriver(DryRunRobotDriver):
    async def connect(self) -> None:
        await asyncio.sleep(0.01)
        await super().connect()


def test_connect_and_disconnect_share_one_command_lock(tmp_path: Path) -> None:
    def factory(
        robot_id: RobotId,
        profile: RobotProfile,
        positions: dict[str, float] | None,
    ) -> RobotDriver:
        return SlowDryRunDriver(robot_id, profile, positions)

    service = make_service(tmp_path, driver_factory=factory)

    async def scenario() -> None:
        connect_task = asyncio.create_task(service.connect())
        await asyncio.sleep(0)
        disconnect_task = asyncio.create_task(service.disconnect())
        await asyncio.gather(connect_task, disconnect_task)
        assert (await service.get_status()).connection_state is RobotConnectionState.DISCONNECTED

    asyncio.run(scenario())


class FailConnectDriver(DryRunRobotDriver):
    async def connect(self) -> None:
        raise RuntimeError("synthetic connect failure")


def test_faulted_robot_can_disconnect_back_to_a_safe_state(tmp_path: Path) -> None:
    def factory(
        robot_id: RobotId,
        profile: RobotProfile,
        positions: dict[str, float] | None,
    ) -> RobotDriver:
        return FailConnectDriver(robot_id, profile, positions)

    service = make_service(tmp_path, driver_factory=factory)

    async def scenario() -> None:
        with pytest.raises(RobotApplicationError, match="connection failed"):
            await service.connect()
        faulted = await service.get_status()
        assert faulted.connection_state is RobotConnectionState.FAULTED
        assert faulted.last_error == "Dry Run connect failed: RuntimeError"
        recovered = await service.disconnect()
        assert recovered.connection_state is RobotConnectionState.DISCONNECTED
        assert recovered.last_error is None

    asyncio.run(scenario())


def test_state_sequence_is_monotonic_across_commands(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    async def scenario() -> None:
        sequences = [(await service.get_status()).state_sequence]
        sequences.append((await service.stop()).status.state_sequence)
        sequences.append((await service.connect()).state_sequence)
        sequences.append((await service.stop()).status.state_sequence)
        sequences.append((await service.disconnect()).state_sequence)
        sequences.append((await service.switch_variant(RobotVariant.V1)).state_sequence)
        assert sequences == sorted(sequences)
        assert len(sequences) == len(set(sequences))

    asyncio.run(scenario())


def test_dry_run_driver_persists_without_changing_position_on_stop(tmp_path: Path) -> None:
    profile = FileProfileRepository(repository_root() / "robot_profiles").get(RobotVariant.V1)
    repository = FileRuntimeStateRepository(tmp_path)
    driver = DryRunRobotDriver("primary", profile, runtime_repository=repository)

    async def scenario() -> None:
        before = await driver.read_joint_state()
        await driver.connect()
        await driver.stop()
        after = await driver.read_joint_state()
        assert after == before
        restored = repository.load("primary")
        assert restored is not None
        assert restored.connection_state is RobotConnectionState.CONNECTED
        assert restored.positions == before.positions
        assert driver.hardware_accessed is False

    asyncio.run(scenario())
