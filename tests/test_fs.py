import os
from pathlib import Path

import pytest

from app.fs import list_dir, nearest_existing_dir, resolve_path


@pytest.mark.parametrize("raw,expected", [
    (None, "/"), ("", "/"), ("etc", "/etc"), ("/tmp/", "/tmp"),
    ("//tmp//x", "/tmp/x"), ("/a/b/../c", "/a/c"),
])
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
        ("A", True), ("b", True), ("B.txt", False), ("c.txt", False),
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
