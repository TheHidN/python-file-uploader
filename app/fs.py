"""Filesystem operations for the uploader. No Flask imports: keep this testable on its own."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Entry:
    name: str
    is_dir: bool
    size: int | None
    mtime: float | None


def resolve_path(raw: str | None) -> Path:
    """Absolute, normalized path; empty means `/`, relative is taken from `/`.

    Symlinks are left alone so the breadcrumb shows the path as typed.
    """
    joined = os.path.join("/", raw or "")
    # normpath keeps a leading "//" (POSIX allows it to be special); collapse it.
    return Path("/" + os.path.normpath(joined).lstrip("/"))


def nearest_existing_dir(path: Path) -> Path:
    """`path` itself if it is a directory, else the closest ancestor that is."""
    for candidate in (path, *path.parents):
        if candidate.is_dir():
            return candidate
    return Path("/")


def list_dir(path: Path) -> list[Entry]:
    """Folders first, then files, each sorted case-insensitively.

    Raises FileNotFoundError, NotADirectoryError, or PermissionError/OSError.
    """
    entries = []
    with os.scandir(path) as it:
        for de in it:
            try:
                st = de.stat()  # follows symlinks
            except OSError:
                entries.append(Entry(de.name, de.is_dir(follow_symlinks=False), None, None))
                continue
            is_dir = de.is_dir()
            entries.append(Entry(de.name, is_dir, None if is_dir else st.st_size, st.st_mtime))
    entries.sort(key=lambda e: (not e.is_dir, e.name.casefold()))
    return entries
