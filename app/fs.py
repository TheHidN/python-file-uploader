"""Filesystem operations for the uploader. No Flask imports: keep this testable on its own."""

import os
import re
import secrets
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


@dataclass(frozen=True)
class FileResult:
    name: str
    status: str  # "saved", "skipped (exists)", or "failed: <reason>"


def clean_filename(raw: str | None) -> str:
    """Keep only the final path component; spaces etc. are kept as given."""
    name = re.split(r"[/\\]", raw or "")[-1]
    if name in ("", ".", "..") or "\x00" in name:
        raise ValueError("invalid filename")
    return name


def ensure_dir(path: Path, create: bool) -> None:
    """Make sure `path` is a directory, creating it (and parents) if allowed."""
    if path.is_dir():
        return
    if path.exists():
        raise NotADirectoryError(f"Not a directory: {path}")
    if not create:
        raise FileNotFoundError(f"Directory does not exist: {path}")
    path.mkdir(parents=True, exist_ok=True)


def save_file(storage, target_dir: Path, overwrite: bool) -> FileResult:
    """Save one upload into `target_dir`. Never raises; failures are reported in the result.

    `storage` is anything with `.filename` and `.save(dst)`, e.g. werkzeug's FileStorage.
    """
    try:
        name = clean_filename(storage.filename)
    except ValueError as e:
        return FileResult(storage.filename or "", f"failed: {e}")
    dst = target_dir / name
    if dst.is_dir():
        return FileResult(name, "failed: is a directory")
    if dst.exists() and not overwrite:
        return FileResult(name, "skipped (exists)")
    # Write beside the target, then swap it in: a failed upload never clobbers or truncates `dst`.
    tmp = target_dir / f".{name}.{secrets.token_hex(4)}.part"
    try:
        os.close(os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666))  # honours umask
        storage.save(str(tmp))
        os.replace(tmp, dst)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        return FileResult(name, f"failed: {e.strerror or e}")
    return FileResult(name, "saved")
