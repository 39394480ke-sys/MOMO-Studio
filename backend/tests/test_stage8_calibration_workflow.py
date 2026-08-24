"""Stage 8 calibration workflow tests; every hardware boundary is an in-memory fake."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import NoReturn, cast
from uuid import uuid4

import pytest

from momo.adapters.storage.file_calibration_workflow_repository import (
    FileCalibrationWorkflowRepository,
)
from momo.application.services.calibration_workflow_service import (
    CALIBRATION_JOINT_CONFIRMATION,
    LEGACY_IMPORT_CONFIRMATION,
    ROLLBACK_CONFIRMATION,
    SAVE_CALIBRATION_CONFIRMATION,
    CalibrationWorkflowService,
)
from momo.domain.calibration import CalibrationDocument
from momo.domain.calibration_workflow import (
    CalibrationAuthorization,
    CalibrationRevisionRecord,
    CalibrationWorkflowError,
    CalibrationWorkflowSource,
    CalibrationWorkflowState,
    calibration_document_fingerprint,
)
from momo.domain.enums import ControlMode, DomainUnit, HardwareAccessPolicy, RobotVariant
from momo.domain.real_hardware import (
    RealHardwareAuthorizationPurpose,
    RealHardwareCapabilityReadiness,
    RealStopOutcome,
    ServoPingResult,
    ServoWriteResult,
)
from momo.domain.robot import RobotProfile
from tests.stage3_helpers import FakeClock
from tests.stage8_hardware_helpers import real_calibration, real_profile


class ReadOnlyCalibrationBus:
    """Fail loudly if the calibration service calls anything except one-ID position read."""

    def __init__(self, positions: Mapping[int, int]) -> None:
        self.positions = dict(positions)
        self.reads: list[tuple[int, ...]] = []
        self.forbidden_calls: list[str] = []

    async def read_present_positions(self, servo_ids: tuple[int, ...]) -> Mapping[int, int]:
        self.reads.append(servo_ids)
        return {servo_id: self.positions[servo_id] for servo_id in servo_ids}

    async def open(self, device: str, protocol: str) -> NoReturn:
        del device, protocol
        self._forbidden("open")

    async def close(self) -> NoReturn:
        self._forbidden("close")

    async def ping_explicit_ids(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, ServoPingResult]:
        del servo_ids
        self._forbidden("ping_explicit_ids")

    async def read_operating_modes(self, servo_ids: tuple[int, ...]) -> Mapping[int, str]:
        del servo_ids
        self._forbidden("read_operating_modes")

    async def read_torque_states(self, servo_ids: tuple[int, ...]) -> Mapping[int, bool]:
        del servo_ids
        self._forbidden("read_torque_states")

    async def write_goal_positions(
        self,
        goal_positions: Mapping[int, int],
    ) -> ServoWriteResult:
        del goal_positions
        self._forbidden("write_goal_positions")

    async def stop_or_hold(self, servo_ids: tuple[int, ...]) -> RealStopOutcome:
        del servo_ids
        self._forbidden("stop_or_hold")

    def _forbidden(self, name: str) -> NoReturn:
        self.forbidden_calls.append(name)
        raise AssertionError(f"calibration workflow must never call {name}")


def authorization_for(
    calibration: CalibrationDocument | None,
    *,
    clock: FakeClock,
    profile: RobotProfile | None = None,
    expires_in_s: float = 60.0,
) -> CalibrationAuthorization:
    resolved_profile = profile or real_profile()
    return CalibrationAuthorization(
        session_id=uuid4(),
        robot_id="primary",
        variant=resolved_profile.variant,
        profile_fingerprint=resolved_profile.fingerprint,
        calibration_fingerprint=(
            calibration_document_fingerprint(calibration) if calibration is not None else None
        ),
        allowed_servo_ids=tuple(
            cast(int, definition.servo_id) for definition in resolved_profile.joint_definitions
        ),
        issued_at=clock.now(),
        expires_at=clock.now() + timedelta(seconds=expires_in_s),
        confirmed=True,
        physical_estop_confirmed=True,
        control_mode=ControlMode.REAL,
        hardware_policy=HardwareAccessPolicy.READ_ONLY,
        purpose=RealHardwareAuthorizationPurpose.CALIBRATION_CAPTURE,
        capabilities=RealHardwareCapabilityReadiness(
            commissioning_diagnostics_ready=True,
            calibration_capture_ready=True,
        ),
    )


def seeded_repository(
    directory: Path,
    calibration: CalibrationDocument,
    clock: FakeClock,
) -> FileCalibrationWorkflowRepository:
    repository = FileCalibrationWorkflowRepository(directory)
    repository.save_new(
        calibration,
        expected_revision=None,
        source=CalibrationWorkflowSource.EXISTING_REAL,
        created_at=clock.now(),
    )
    return repository


def test_calibration_bundle_import_is_all_or_none_for_explicit_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    v2 = real_calibration(real_profile())
    v1 = v2.model_copy(update={"id": uuid4(), "robot_variant": RobotVariant.V1})
    repository = FileCalibrationWorkflowRepository(tmp_path / "failed-import")
    original_replace = repository._atomic_replace
    replacements = 0

    def fail_second(destination: Path, payload: bytes) -> None:
        nonlocal replacements
        replacements += 1
        if replacements == 2:
            raise OSError("synthetic second calibration write failure")
        original_replace(destination, payload)

    monkeypatch.setattr(repository, "_atomic_replace", fail_second)
    with pytest.raises(OSError, match="second calibration"):
        repository.import_new_bundle((v2, v1), created_at=clock.now())
    assert repository.get_revision(RobotVariant.V1) is None
    assert repository.get_revision(RobotVariant.V2) is None

    durability = FileCalibrationWorkflowRepository(tmp_path / "durability-import")
    durability._ensure_directory()
    original_fsync = durability._fsync_directory
    fsync_calls = 0

    def fail_first_directory_fsync(directory: Path) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            raise OSError("synthetic post-replace calibration fsync failure")
        original_fsync(directory)

    monkeypatch.setattr(durability, "_fsync_directory", fail_first_directory_fsync)
    with pytest.raises(OSError, match="durability is uncertain"):
        durability.import_new_bundle((v2, v1), created_at=clock.now())
    assert fsync_calls >= 2
    assert durability.get_revision(RobotVariant.V1) is None
    assert durability.get_revision(RobotVariant.V2) is None

    successful = FileCalibrationWorkflowRepository(tmp_path / "successful-import")
    records = successful.import_new_bundle((v2, v1), created_at=clock.now())
    assert {record.calibration.robot_variant for record in records} == {
        RobotVariant.V1,
        RobotVariant.V2,
    }
    assert all(record.revision == 1 for record in records)


def test_selected_joint_reads_are_one_id_only_and_complete_creates_atomic_revision(
    tmp_path: Path,
) -> None:
    async def scenario() -> tuple[
        CalibrationRevisionRecord,
        CalibrationRevisionRecord,
        ReadOnlyCalibrationBus,
        Path,
    ]:
        clock = FakeClock()
        profile = real_profile()
        calibration = real_calibration(profile)
        repository = seeded_repository(tmp_path / "runtime-calibrations", calibration, clock)
        positions = {
            definition.servo_id: 100 + index
            for index, definition in enumerate(profile.joint_definitions)
            if definition.servo_id is not None
        }
        bus = ReadOnlyCalibrationBus(positions)
        service = CalibrationWorkflowService(repository, bus, clock)
        authorization = authorization_for(calibration, clock=clock)
        status = await service.start(authorization, profile)

        for index, definition in enumerate(profile.joint_definitions):
            await service.read_selected_joint(
                status.session_id,
                authorization,
                definition.joint_id,
            )
            preview = await service.preview_joint(
                status.session_id,
                authorization,
                definition.joint_id,
                logical_value=1.0 if index == 0 else 0.0,
                direction=-1 if index == 0 else 1,
                phase=index,
                raw_bounds=(-20_000, 20_000),
            )
            servo_id = cast(int, definition.servo_id)
            assert preview.observed_raw == positions[servo_id]
            assert preview.direction == (-1 if index == 0 else 1)
            assert preview.phase == index
            status = await service.confirm_joint(
                status.session_id,
                authorization,
                definition.joint_id,
                preview_fingerprint=preview.preview_fingerprint,
                confirmation=CALIBRATION_JOINT_CONFIRMATION,
            )

        assert status.state is CalibrationWorkflowState.READY_TO_SAVE
        assert status.save_preview is not None
        assert tuple(
            joint.joint_id for joint in status.save_preview.proposed_calibration.joints
        ) == tuple(profile.enabled_joints)
        with pytest.raises(CalibrationWorkflowError) as confirmation_error:
            await service.complete(
                status.session_id,
                authorization,
                proposed_calibration_fingerprint=(
                    status.save_preview.proposed_calibration_fingerprint
                ),
                confirmation="save calibration",
            )
        assert confirmation_error.value.code == "CALIBRATION_SAVE_CONFIRMATION_REQUIRED"
        with pytest.raises(CalibrationWorkflowError) as fingerprint_error:
            await service.complete(
                status.session_id,
                authorization,
                proposed_calibration_fingerprint="f" * 64,
                confirmation=SAVE_CALIBRATION_CONFIRMATION,
            )
        assert fingerprint_error.value.code == "CALIBRATION_SAVE_PREVIEW_CHANGED"
        saved = await service.complete(
            status.session_id,
            authorization,
            proposed_calibration_fingerprint=(status.save_preview.proposed_calibration_fingerprint),
            confirmation=SAVE_CALIBRATION_CONFIRMATION,
        )
        backup_directory = repository.backup_directory / profile.variant.value.lower()
        backup = next(backup_directory.iterdir())
        current = repository.get_revision(profile.variant)
        assert current is not None
        return saved, current, bus, backup

    saved, current, bus, backup = asyncio.run(scenario())

    assert saved == current
    assert saved.revision == 2
    assert saved.previous_calibration_fingerprint is not None
    assert saved.calibration_fingerprint != saved.previous_calibration_fingerprint
    assert backup.name.startswith("00000001-")
    assert backup.is_file()
    assert all(len(ids) == 1 for ids in bus.reads)
    assert len(bus.reads) == len(real_profile().enabled_joints)
    assert bus.forbidden_calls == []


@pytest.mark.parametrize("variant", [RobotVariant.V1, RobotVariant.V2])
def test_empty_repository_builds_incomplete_draft_then_saves_revision_one(
    tmp_path: Path,
    variant: RobotVariant,
) -> None:
    async def scenario() -> tuple[
        CalibrationRevisionRecord,
        ReadOnlyCalibrationBus,
        RobotProfile,
    ]:
        clock = FakeClock()
        profile = real_profile(variant)
        repository = FileCalibrationWorkflowRepository(tmp_path / "fresh-commissioning")
        positions = {
            cast(int, definition.servo_id): 100 + index
            for index, definition in enumerate(profile.joint_definitions)
        }
        bus = ReadOnlyCalibrationBus(positions)
        service = CalibrationWorkflowService(repository, bus, clock)
        authorization = authorization_for(None, clock=clock, profile=profile)

        status = await service.start(authorization, profile)
        assert status.base_revision is None
        assert status.base_calibration_fingerprint is None
        assert status.draft.base_revision is None
        assert tuple(joint.joint_id for joint in status.draft.joints) == tuple(
            profile.enabled_joints
        )
        assert all(
            joint.present_raw is None
            and joint.logical_value is None
            and joint.direction is None
            and joint.phase is None
            and joint.raw_bounds is None
            and joint.operating_mode is None
            for joint in status.draft.joints
        )
        assert not hasattr(service.servo_bus, "write_goal_positions")
        assert not hasattr(service.servo_bus, "stop_or_hold")
        assert not hasattr(service.servo_bus, "scan")

        for definition in profile.joint_definitions:
            assert definition.servo_id is not None
            assert definition.raw_bounds is not None
            status = await service.read_selected_joint(
                status.session_id,
                authorization,
                definition.joint_id,
            )
            draft_joint = status.draft.joints_by_id[definition.joint_id]
            assert draft_joint.present_raw == positions[definition.servo_id]
            assert draft_joint.logical_value is None
            preview = await service.preview_joint(
                status.session_id,
                authorization,
                definition.joint_id,
                logical_value=0.0,
                direction=1,
                phase=0,
                raw_bounds=definition.raw_bounds,
            )
            status = await service.confirm_joint(
                status.session_id,
                authorization,
                definition.joint_id,
                preview_fingerprint=preview.preview_fingerprint,
                confirmation=CALIBRATION_JOINT_CONFIRMATION,
            )

        assert status.state is CalibrationWorkflowState.READY_TO_SAVE
        assert status.save_preview is not None
        assert status.save_preview.base_revision is None
        assert status.save_preview.base_calibration_fingerprint is None
        saved = await service.complete(
            status.session_id,
            authorization,
            proposed_calibration_fingerprint=(status.save_preview.proposed_calibration_fingerprint),
            confirmation=SAVE_CALIBRATION_CONFIRMATION,
        )
        return saved, bus, profile

    saved, bus, profile = asyncio.run(scenario())

    assert saved.revision == 1
    assert saved.previous_calibration_fingerprint is None
    assert saved.calibration.template is False
    assert saved.calibration.profile_fingerprint == profile.fingerprint
    assert tuple(joint.joint_id for joint in saved.calibration.joints) == tuple(
        profile.enabled_joints
    )
    assert tuple(profile.enabled_joints) == (
        ("j11", "j12", "j13", "j14", "j15")
        if variant is RobotVariant.V1
        else ("j10", "j11", "j12", "j13", "j14", "j15")
    )
    for definition in profile.joint_definitions:
        assert definition.domain_unit is (
            DomainUnit.MM if definition.joint_id == "j10" else DomainUnit.DEG
        )
    assert bus.forbidden_calls == []
    assert all(len(ids) == 1 for ids in bus.reads)


def test_rollback_is_forward_only_and_backs_up_the_replaced_revision(tmp_path: Path) -> None:
    async def scenario() -> tuple[
        CalibrationRevisionRecord,
        CalibrationRevisionRecord,
        tuple[Path, ...],
    ]:
        clock = FakeClock()
        profile = real_profile()
        initial = real_calibration(profile)
        repository = seeded_repository(tmp_path, initial, clock)
        replacement = initial.model_copy(
            update={
                "id": uuid4(),
                "notes": "synthetic replacement",
                "joints": [
                    joint.model_copy(update={"home_present_raw": 5}) for joint in initial.joints
                ],
            }
        )
        revision_two = repository.save_new(
            CalibrationDocument.model_validate(replacement.model_dump()),
            expected_revision=1,
            source=CalibrationWorkflowSource.EXISTING_REAL,
            created_at=clock.now(),
        )
        bus = ReadOnlyCalibrationBus({})
        service = CalibrationWorkflowService(repository, bus, clock)
        authorization = authorization_for(revision_two.calibration, clock=clock)
        rolled_back = await service.rollback(
            authorization,
            profile,
            target_revision=1,
            confirmation=ROLLBACK_CONFIRMATION,
        )
        backups = tuple(
            sorted((repository.backup_directory / profile.variant.value.lower()).iterdir())
        )
        return revision_two, rolled_back, backups

    revision_two, rolled_back, backups = asyncio.run(scenario())

    assert rolled_back.revision == 3
    assert rolled_back.previous_calibration_fingerprint == revision_two.calibration_fingerprint
    assert rolled_back.calibration.id != revision_two.calibration.id
    assert all(joint.home_present_raw == 0 for joint in rolled_back.calibration.joints)
    assert [path.name[:8] for path in backups] == ["00000001", "00000002"]


def test_template_legacy_import_and_expired_authorization_fail_before_bus_access(
    tmp_path: Path,
) -> None:
    async def scenario() -> tuple[list[str], list[tuple[int, ...]]]:
        clock = FakeClock()
        profile = real_profile()
        calibration = real_calibration(profile)
        repository = seeded_repository(tmp_path, calibration, clock)
        bus = ReadOnlyCalibrationBus(
            {
                definition.servo_id: 0
                for definition in profile.joint_definitions
                if definition.servo_id is not None
            }
        )
        service = CalibrationWorkflowService(repository, bus, clock)
        codes: list[str] = []
        wrong_purpose = authorization_for(calibration, clock=clock).model_copy(
            update={"purpose": RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION}
        )
        with pytest.raises(CalibrationWorkflowError) as purpose_error:
            await service.start(wrong_purpose, profile)
        codes.append(purpose_error.value.code)
        template = calibration.model_copy(update={"template": True, "id": uuid4()})
        with pytest.raises(CalibrationWorkflowError) as template_error:
            await service.start(
                authorization_for(calibration, clock=clock),
                profile,
                source=CalibrationWorkflowSource.EXPLICIT_LEGACY_IMPORT,
                explicit_legacy_calibration=CalibrationDocument.model_validate(
                    template.model_dump()
                ),
                legacy_confirmation=LEGACY_IMPORT_CONFIRMATION,
            )
        codes.append(template_error.value.code)

        active_then_expired = authorization_for(calibration, clock=clock, expires_in_s=1.0)
        status = await service.start(active_then_expired, profile)
        await clock.advance(1.0)
        with pytest.raises(CalibrationWorkflowError) as active_expiry_error:
            await service.read_selected_joint(
                status.session_id,
                active_then_expired,
                profile.enabled_joints[0],
            )
        codes.append(active_expiry_error.value.code)

        expired = authorization_for(calibration, clock=clock, expires_in_s=1.0)
        await clock.advance(1.0)
        with pytest.raises(CalibrationWorkflowError) as expiry_error:
            await service.start(expired, profile)
        codes.append(expiry_error.value.code)
        return codes, bus.reads

    codes, reads = asyncio.run(scenario())

    assert codes == [
        "CALIBRATION_AUTHORIZATION_MISMATCH",
        "TEMPLATE_CALIBRATION_FORBIDDEN",
        "CALIBRATION_AUTHORIZATION_EXPIRED",
        "CALIBRATION_AUTHORIZATION_EXPIRED",
    ]
    assert reads == []


def test_confirmation_and_active_steps_are_bound_to_current_revision(tmp_path: Path) -> None:
    async def scenario() -> tuple[str, str, str]:
        clock = FakeClock()
        profile = real_profile()
        calibration = real_calibration(profile)
        repository = seeded_repository(tmp_path, calibration, clock)
        definition = profile.joint_definitions[0]
        assert definition.servo_id is not None
        bus = ReadOnlyCalibrationBus({definition.servo_id: 0})
        service = CalibrationWorkflowService(repository, bus, clock)
        authorization = authorization_for(calibration, clock=clock)
        status = await service.start(authorization, profile)
        await service.read_selected_joint(status.session_id, authorization, definition.joint_id)
        await service.preview_joint(
            status.session_id,
            authorization,
            definition.joint_id,
            logical_value=0.0,
            phase=0,
        )
        with pytest.raises(CalibrationWorkflowError) as confirmation_error:
            await service.confirm_joint(
                status.session_id,
                authorization,
                definition.joint_id,
                preview_fingerprint="f" * 64,
                confirmation=CALIBRATION_JOINT_CONFIRMATION,
            )

        changed = calibration.model_copy(
            update={
                "id": uuid4(),
                "joints": [
                    joint.model_copy(update={"home_present_raw": 1}) for joint in calibration.joints
                ],
            }
        )
        repository.save_new(
            CalibrationDocument.model_validate(changed.model_dump()),
            expected_revision=1,
            source=CalibrationWorkflowSource.EXISTING_REAL,
            created_at=clock.now(),
        )
        with pytest.raises(CalibrationWorkflowError) as workflow_drift_error:
            await service.status(status.session_id, authorization)
        # Complete cannot be reached here, but repository CAS is independently fail-closed.
        with pytest.raises(CalibrationWorkflowError) as cas_error:
            repository.save_new(
                calibration.model_copy(update={"id": uuid4()}),
                expected_revision=1,
                source=CalibrationWorkflowSource.EXISTING_REAL,
                created_at=clock.now(),
            )
        return (
            confirmation_error.value.code,
            workflow_drift_error.value.code,
            cas_error.value.code,
        )

    confirmation_code, workflow_drift_code, cas_code = asyncio.run(scenario())

    assert confirmation_code == "CALIBRATION_PREVIEW_CHANGED"
    assert workflow_drift_code == "CALIBRATION_REVISION_CONFLICT"
    assert cas_code == "CALIBRATION_REVISION_CONFLICT"
