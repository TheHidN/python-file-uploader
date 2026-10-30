from datetime import datetime
from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.fs import list_dir, nearest_existing_dir, resolve_path

bp = Blueprint("main", __name__)


def _crumbs(path: Path) -> list[tuple[str, str]]:
    """(label, path) pairs from `/` down to `path`."""
    chain = [*reversed(path.parents), path] if path != Path("/") else [path]
    return [(p.name or "/", str(p)) for p in chain]


@bp.app_template_filter("filesize")
def _filesize(n: int | None) -> str:
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


@bp.app_template_filter("mtime")
def _mtime(ts: float | None) -> str:
    return "-" if ts is None else datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


@bp.get("/")
def index():
    return redirect(url_for("main.browse", path="/"))


@bp.get("/browse")
def browse():
    path = resolve_path(request.args.get("path"))
    if not path.is_dir():
        flash(f"Not a directory: {path}", "error")
        path = nearest_existing_dir(path)
    try:
        entries = list_dir(path)
    except OSError as e:
        flash(f"Cannot read {path}: {e.strerror or e}", "error")
        entries = []
    return render_template("browse.html", path=path, crumbs=_crumbs(path), entries=entries)
