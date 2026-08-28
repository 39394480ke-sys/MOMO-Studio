"""Directory creation whose parent entries are durable before file commit."""

from __future__ import annotations

import stat
from collections.abc import Callable
from pathlib import Path


def ensure_directory_durable(
    directory: Path,
    *,
    fsync_directory: Callable[[Path], None],
    mode: int | None = None,
) -> None:
    """Create a directory and fsync its full existing parent chain once.

    A file fsync plus an fsync of the new directory does not persist the new
    directory entry in its parent. Walking to the filesystem root also makes a
    retry after an earlier parent-fsync failure safe before callers publish data.
    """

    directory.mkdir(parents=True, exist_ok=True, mode=mode or 0o777)
    metadata = directory.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise OSError("storage directory is not a regular directory")
    if mode is not None:
        directory.chmod(mode)

    current = directory
    while True:
        fsync_directory(current)
        if current.parent == current:
            break
        current = current.parent
