"""Atomic, path-confined JSON persistence for Dry Run runtime state."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from momo.domain.runtime import RuntimeState

_ROBOT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class FileRuntimeStateRepository:
    """Persist one runtime file per safe robot ID using same-directory replace."""

    def __init__(self, directory: Path, *, path_description: str = "data/runtime/robots") -> None:
        self.directory = directory.resolve()
        self._path_description = path_description.strip("/")
        self.last_load_valid = True
        self.last_diagnostic = "No runtime state has been loaded"
        self.last_quarantined_file: str | None = None

    @property
    def path_description(self) -> str:
        return f"{self._path_description}/primary.json"

    def _path(self, robot_id: str) -> Path:
        if not _ROBOT_ID.fullmatch(robot_id):
            raise ValueError("robot_id is not safe for a runtime filename")
        candidate = (self.directory / f"{robot_id}.json").resolve()
        if candidate.parent != self.directory:
            raise ValueError("runtime path escapes its configured directory")
        return candidate

    def load(self, robot_id: str) -> RuntimeState | None:
        path = self._path(robot_id)
        self.last_quarantined_file = None
        if not path.is_file():
            self.last_load_valid = True
            self.last_diagnostic = "No saved runtime state; using profile Home values"
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            state = RuntimeState.model_validate(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
            self.last_load_valid = False
            self.last_diagnostic = (
                f"Runtime state was corrupt and quarantined: {type(error).__name__}"
            )
            self._attempt_quarantine(robot_id)
            return None
        self.last_load_valid = True
        self.last_diagnostic = "Runtime state loaded and validated"
        return state

    def reject_loaded_state(self, robot_id: str, reason: str) -> None:
        self.last_load_valid = False
        self.last_diagnostic = reason
        self._attempt_quarantine(robot_id)

    def _attempt_quarantine(self, robot_id: str) -> None:
        try:
            self.last_quarantined_file = self.quarantine(robot_id)
        except OSError as error:
            self.last_quarantined_file = None
            self.last_diagnostic += f"; quarantine failed: {type(error).__name__}"

    def quarantine(self, robot_id: str) -> str | None:
        source = self._path(robot_id)
        if not source.exists():
            return None
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        destination = source.with_name(f"{robot_id}.quarantine-{timestamp}.json")
        os.replace(source, destination)
        return destination.name

    def save(self, state: RuntimeState) -> None:
        path = self._path(state.robot_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            state.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(payload)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, path)
            temporary_name = None
            self.last_load_valid = True
            self.last_diagnostic = "Runtime state saved and validated"
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
