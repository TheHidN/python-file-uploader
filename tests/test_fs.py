import os
from pathlib import Path

import pytest

from app.fs import (
    FileResult,
    clean_filename,
    ensure_dir,
    list_dir,
    nearest_existing_dir,
    resolve_path,
    save_file,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "/"),
        ("", "/"),
        ("etc", "/etc"),
        ("/tmp/", "/tmp"),
        ("//tmp//x", "/tmp/x"),
        ("/a/b/../c", "/a/c"),
    ],
)
def test_resolve_path_cases(raw, expected):
    assert resolve_path(raw) == Path(expected)


def test_nearest_existing_dir(tmp_path):
    assert nearest_existing_dir(tmp_path / "no" / "such") == tmp_path


def test_nearest_existing_dir_skips_files(tmp_path):
    (tmp_path / "f").write_text("x")
    assert nearest_existing_dir(tmp_path / "f") == tmp_path


def test_list_dir_order_and_fields(tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "A").mkdir()
    (tmp_path / "c.txt").write_text("abc")
    (tmp_path / "B.txt").write_text("")
    entries = list_dir(tmp_path)
    assert [(e.name, e.is_dir) for e in entries] == [
        ("A", True),
        ("b", True),
        ("B.txt", False),
        ("c.txt", False),
    ]
    c = entries[3]
    assert c.size == 3 and c.mtime is not None
    assert entries[0].size is None and entries[0].mtime is not None


def test_list_dir_broken_symlink(tmp_path):
    (tmp_path / "dead").symlink_to(tmp_path / "missing")
    [e] = list_dir(tmp_path)
    assert e.name == "dead" and e.size is None and e.mtime is None and not e.is_dir


def test_list_dir_symlink_to_dir_is_dir(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    assert [(e.name, e.is_dir) for e in list_dir(tmp_path)] == [("link", True), ("real", True)]


def test_list_dir_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        list_dir(tmp_path / "x")


def test_list_dir_on_file_raises(tmp_path):
    (tmp_path / "f").write_text("x")
    with pytest.raises(NotADirectoryError):
        list_dir(tmp_path / "f")


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_list_dir_unreadable_raises(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        with pytest.raises(PermissionError):
            list_dir(locked)
    finally:
        locked.chmod(0o755)


class FakeStorage:
    """Stand-in for werkzeug FileStorage: has .filename and .save(dst)."""

    def __init__(self, filename, data: bytes):
        self.filename = filename
        self.data = data

    def save(self, dst):
        with open(dst, "wb") as f:
            f.write(self.data)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a.txt", "a.txt"),
        ("my file.txt", "my file.txt"),
        ("../../etc/x", "x"),
        ("a/b", "b"),
        (r"C:\Users\me\a b.txt", "a b.txt"),
    ],
)
def test_clean_filename_cases(raw, expected):
    assert clean_filename(raw) == expected


@pytest.mark.parametrize("raw", [None, "", ".", "..", "dir/", "a\x00b"])
def test_clean_filename_rejects(raw):
    with pytest.raises(ValueError):
        clean_filename(raw)


def test_ensure_dir_creates_parents(tmp_path):
    ensure_dir(tmp_path / "a" / "b", create=True)
    assert (tmp_path / "a" / "b").is_dir()


def test_ensure_dir_existing_ok(tmp_path):
    ensure_dir(tmp_path, create=False)


def test_ensure_dir_missing_no_create(tmp_path):
    with pytest.raises(FileNotFoundError):
        ensure_dir(tmp_path / "a", create=False)
    assert not (tmp_path / "a").exists()


def test_ensure_dir_on_file(tmp_path):
    (tmp_path / "f").write_text("x")
    with pytest.raises(NotADirectoryError):
        ensure_dir(tmp_path / "f", create=True)


def test_save_file_saved(tmp_path):
    r = save_file(FakeStorage("a.txt", b"hi"), tmp_path, overwrite=False)
    assert r == FileResult("a.txt", "saved")
    assert (tmp_path / "a.txt").read_bytes() == b"hi"


def test_save_file_skips_existing(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"old")
    r = save_file(FakeStorage("a.txt", b"new"), tmp_path, overwrite=False)
    assert r == FileResult("a.txt", "skipped (exists)")
    assert (tmp_path / "a.txt").read_bytes() == b"old"


def test_save_file_overwrites(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"old")
    r = save_file(FakeStorage("a.txt", b"new"), tmp_path, overwrite=True)
    assert r == FileResult("a.txt", "saved")
    assert (tmp_path / "a.txt").read_bytes() == b"new"


def test_save_file_traversal_stays_in_dir(tmp_path):
    target = tmp_path / "t"
    target.mkdir()
    r = save_file(FakeStorage("../evil.txt", b"x"), target, overwrite=False)
    assert r == FileResult("evil.txt", "saved")
    assert (target / "evil.txt").exists() and not (tmp_path / "evil.txt").exists()


def test_save_file_invalid_name(tmp_path):
    r = save_file(FakeStorage("..", b"x"), tmp_path, overwrite=False)
    assert r.name == ".." and r.status.startswith("failed: ")


def test_save_file_none_name(tmp_path):
    r = save_file(FakeStorage(None, b"x"), tmp_path, overwrite=False)
    assert r.name == "" and r.status.startswith("failed: ")


def test_save_file_onto_directory_fails(tmp_path):
    (tmp_path / "d").mkdir()
    r = save_file(FakeStorage("d", b"x"), tmp_path, overwrite=True)
    assert r == FileResult("d", "failed: is a directory")


def test_save_file_os_error_reported(tmp_path):
    r = save_file(FakeStorage("a.txt", b"x"), tmp_path / "missing", overwrite=False)
    assert r.name == "a.txt" and r.status.startswith("failed: ")


class FailingStorage(FakeStorage):
    """Writes part of the data, then fails like a full disk."""

    def save(self, dst):
        with open(dst, "wb") as f:
            f.write(self.data[:1])
        raise OSError(28, "No space left on device")


def test_save_file_failed_overwrite_keeps_original(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"original")
    r = save_file(FailingStorage("a.txt", b"new data"), tmp_path, overwrite=True)
    assert r == FileResult("a.txt", "failed: No space left on device")
    assert (tmp_path / "a.txt").read_bytes() == b"original"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.txt"]


def test_save_file_failed_new_file_leaves_nothing(tmp_path):
    r = save_file(FailingStorage("a.txt", b"new data"), tmp_path, overwrite=False)
    assert r.status.startswith("failed: ")
    assert list(tmp_path.iterdir()) == []
