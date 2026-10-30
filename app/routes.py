from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from app.fs import ensure_dir, list_dir, nearest_existing_dir, resolve_path, save_file

bp = Blueprint("main", __name__)


def _crumbs(path: Path) -> list[tuple[str, str]]:
    """(label, path) pairs from `/` down to `path`."""
    chain = [*reversed(path.parents), path] if path != Path("/") else [path]
    return [(p.name or "/", str(p)) for p in chain]


@bp.app_template_filter("filesize")
def _filesize(n: int | None) -> str:
    if n is None:
        return "-"
    size: float = n
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


@bp.app_template_filter("mtime")
def _mtime(ts: float | None) -> str:
    return "-" if ts is None else datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


@bp.before_app_request
def _reject_cross_site_writes():
    """Stop other web pages from making the operator's browser POST here (CSRF)."""
    if request.method != "POST":
        return
    if request.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
        abort(403)
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).netloc != request.host:
        abort(403)


def _finish(url: str, status: int = 200):
    """Send the browser to `url`: a redirect for forms, JSON for the drag-and-drop script.

    The script navigates itself, so the flashed results survive until the page that shows them.
    """
    if request.accept_mimetypes.best_match(["text/html", "application/json"]) == "application/json":
        return jsonify(redirect=url), status
    return redirect(url)


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


@bp.post("/upload")
def upload():
    try:
        form, uploads = request.form, request.files.getlist("files")
    except OSError as e:  # e.g. the temp dir filled up while receiving the body
        flash(f"Upload failed: {e.strerror or e}", "error")
        return _finish(url_for("main.index"))
    target = resolve_path(form.get("path"))
    back = _finish(url_for("main.browse", path=str(target)))
    files = [f for f in uploads if f.filename]
    if not files:
        flash("No files selected", "error")
        return back
    try:
        ensure_dir(target, create="create_dirs" in form)
    except FileNotFoundError:
        flash(f"Directory does not exist: {target} (tick 'Create folder' to create it)", "error")
        return back
    except NotADirectoryError:
        flash(f"Not a directory: {target}", "error")
        return back
    except OSError as e:
        flash(f"Cannot use {target}: {e.strerror or e}", "error")
        return back
    overwrite = "overwrite" in form
    for f in files:
        result = save_file(f, target, overwrite)
        flash(f"{result.name}: {result.status}", "ok" if result.status == "saved" else "error")
    return back


@bp.app_errorhandler(RequestEntityTooLarge)
def too_large(e):
    # The form can't be read past the limit, so the target path is unknown.
    limit = current_app.config.get("MAX_CONTENT_LENGTH")
    if limit:
        flash(f"Upload exceeds the {limit // (1024 * 1024)} MB limit", "error")
    else:
        flash("Upload rejected: too large or too many parts", "error")
    return _finish(url_for("main.index"), 413)
