# File Uploader Implementation Plan

**Goal:** A Flask web app at `http://<server-ip>:8000` that browses this server's folders and uploads files into any of them. It runs as root and has no login.

**Architecture:** `app/fs.py` holds every filesystem operation and imports nothing from Flask. `app/routes.py` is a thin blueprint that parses requests, calls `fs`, and renders a single Jinja template (`browse.html`). `create_app()` in `app/__init__.py` loads config from the environment. Gunicorn serves the app, started by hand with `sudo ./run.sh`.

**Tech Stack:** Python 3.14, Flask 3.x, Gunicorn, pytest. Dependencies live in a project-local `.venv/`.

**Spec:** `docs/specs/2026-10-30-file-uploader-design.md`

## Global Constraints

- Bind to `0.0.0.0:8000`.
- No authentication. The process runs as root, started with `sudo ./run.sh`. There is no systemd unit.
- Do not use `secure_filename`. Keep the final path component exactly as given, spaces included.
- Per-file status strings must be exactly `saved`, `skipped (exists)`, or `failed: <reason>`.
- `MAX_UPLOAD_MB` is unset by default, meaning no size limit. When set, `MAX_CONTENT_LENGTH = int(MAX_UPLOAD_MB) * 1024 * 1024`.
- `SECRET_KEY` comes from the environment. If it is unset, use `secrets.token_hex(32)`.
- Every expected failure becomes a flash message. The user never sees a stack trace.
- Git uses GitHub flow. All work goes on `feat/file-upload-app` with Conventional Commit messages, and nothing is committed directly to `main`.
- Tests run as the normal user against `tmp_path`, never against real system directories.

## Review Focus

1. **Relative or empty `path`** (`?path=`, `?path=etc`, a trailing `/`, or `//`). Expected: an empty path means `/`, and a relative path is resolved against `/`, not against the process's working directory. Covered by Task 2, `test_resolve_path_*`.
2. **Upload where a directory already has the file's name** (with overwrite ticked). Expected: that file is reported as `failed: …` and the request doesn't crash. Covered by Task 3, `test_save_file_onto_directory_fails`.
3. **Target path is an existing regular file**, with `create_dirs` ticked. Expected: an error flash and no files written. Covered by Task 5, `test_upload_target_is_file`.
4. **Windows-style client filename** (`C:\Users\me\a b.txt`). Expected: saved as `a b.txt`. Covered by Task 3, `test_clean_filename_cases`.
5. **Filenames with HTML in them** (`<script>.txt`) shown in a listing or a flash message. Expected: the name is escaped and shown as text. Covered by Task 4, `test_browse_escapes_names`.

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Project metadata and dependencies (`flask`, `gunicorn`; dev: `pytest`). |
| `.gitignore` | `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/` |
| `app/__init__.py` | `create_app(config: dict \| None = None) -> Flask` |
| `app/fs.py` | Path resolution, directory listing, filename cleaning, saving files |
| `app/routes.py` | Blueprint `bp` with `/`, `/browse`, `/upload`, and the 413 handler |
| `app/templates/browse.html` | Breadcrumb, path box, flash messages, listing table, upload form |
| `tests/conftest.py` | `app` and `client` fixtures |
| `tests/test_app.py`, `tests/test_fs.py`, `tests/test_routes.py` | Tests |
| `run.sh` | `exec .venv/bin/gunicorn -b 0.0.0.0:8000 -w 2 --access-logfile - "app:create_app()"` |
| `README.md` | Setup, how to run, the accepted risk, the optional `ufw` rule |

---

### Task 1: Project scaffold and app factory

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `app/__init__.py`, `app/routes.py` (an empty blueprint for now), `tests/conftest.py`, `tests/test_app.py`

**Interfaces:**
- Produces: `create_app(config: dict | None = None) -> flask.Flask`. It reads `SECRET_KEY` and `MAX_UPLOAD_MB` from `os.environ`, applies any `config` overrides last, and registers `app.routes.bp`.
- Produces: the fixtures `app` (with `TESTING=True`) and `client`, in `tests/conftest.py`.

- [ ] **Step 1: Install the system prerequisite and create the venv**

Run: `sudo apt-get install -y python3.14-venv && python3 -m venv .venv`
Expected: `.venv/bin/pip` exists.

- [ ] **Step 2: Write `pyproject.toml` and `.gitignore`, then install**

`pyproject.toml` contains:
- `[project] name = "file-uploader"`, `requires-python = ">=3.12"`, `dependencies = ["flask>=3.0", "gunicorn>=22"]`
- `[project.optional-dependencies] dev = ["pytest>=8"]`
- `[tool.setuptools] packages = ["app"]`
- `[tool.pytest.ini_options] testpaths = ["tests"]`

Run: `.venv/bin/pip install -e '.[dev]'`
Expected: Flask, Gunicorn, and pytest install.

- [ ] **Step 3: Write the failing tests in `tests/test_app.py`**

```python
def test_secret_key_from_env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "abc")
    assert create_app().config["SECRET_KEY"] == "abc"

def test_secret_key_random_when_unset(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    k1, k2 = create_app().config["SECRET_KEY"], create_app().config["SECRET_KEY"]
    assert len(k1) == 64 and k1 != k2

def test_no_upload_limit_by_default(monkeypatch):
    monkeypatch.delenv("MAX_UPLOAD_MB", raising=False)
    assert create_app().config["MAX_CONTENT_LENGTH"] is None

def test_upload_limit_from_env(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "5")
    assert create_app().config["MAX_CONTENT_LENGTH"] == 5 * 1024 * 1024
```

- [ ] **Step 4: Run the tests and confirm they fail**

Run: `.venv/bin/pytest tests/test_app.py -v`
Expected: the tests fail with an `ImportError` for `create_app`.

- [ ] **Step 5: Implement `create_app` and an empty `bp = Blueprint("main", __name__)`**

Add `conftest.py` with the `app` fixture (`create_app({"TESTING": True})`) and the `client` fixture (`app.test_client()`).

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `.venv/bin/pytest -v`
Expected: 4 tests pass.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore app tests
git commit -m "feat: scaffold flask app factory with env config"
```

---

### Task 2: Path resolution and directory listing (`fs.py`)

**Files:**
- Create: `app/fs.py`, `tests/test_fs.py`

**Interfaces:**
- Produces: `resolve_path(raw: str | None) -> pathlib.Path`. Empty or `None` becomes `/`. A relative path is joined onto `/`. The result is normalized with `os.path.normpath`, so `..`, `//`, and trailing slashes are collapsed. Symlinks are not resolved, so the breadcrumb keeps the path the user typed.
- Produces: `nearest_existing_dir(path: Path) -> Path`. Walks up through parents until it finds one where `is_dir()` is true, ending at `/`.
- Produces: the frozen dataclass `Entry(name: str, is_dir: bool, size: int | None, mtime: float | None)`.
- Produces: `list_dir(path: Path) -> list[Entry]`. Folders come first, then files, each group sorted with `name.casefold()`. An entry whose `stat` fails gets `size=None, mtime=None`, and `is_dir` is then decided without following the symlink. Raises `FileNotFoundError`, `NotADirectoryError`, or `PermissionError`/`OSError`. Uses `os.scandir`. A symlink pointing to a folder counts as a folder.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("raw,expected", [
    (None, "/"), ("", "/"), ("etc", "/etc"), ("/tmp/", "/tmp"),
    ("//tmp//x", "/tmp/x"), ("/a/b/../c", "/a/c"),
])
def test_resolve_path_cases(raw, expected):
    assert resolve_path(raw) == Path(expected)

def test_nearest_existing_dir(tmp_path):
    assert nearest_existing_dir(tmp_path / "no" / "such") == tmp_path

def test_list_dir_order_and_fields(tmp_path):
    # create dirs "b", "A"; files "c.txt" (3 bytes), "B.txt"
    names = [(e.name, e.is_dir) for e in list_dir(tmp_path)]
    assert names == [("A", True), ("b", True), ("B.txt", False), ("c.txt", False)]
    # c.txt entry has size == 3 and mtime not None; dir entries have size None

def test_list_dir_broken_symlink(tmp_path):
    (tmp_path / "dead").symlink_to(tmp_path / "missing")
    [e] = list_dir(tmp_path)
    assert e.name == "dead" and e.size is None and e.mtime is None

def test_list_dir_symlink_to_dir_is_dir(tmp_path): ...  # is_dir True

def test_list_dir_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError): list_dir(tmp_path / "x")

def test_list_dir_on_file_raises(tmp_path):
    with pytest.raises(NotADirectoryError): ...

@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_list_dir_unreadable_raises(tmp_path):
    # chmod 0o000 on a subdir, expect PermissionError, restore mode in finally
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/pytest tests/test_fs.py -v`
Expected: the tests fail with an `ImportError`.

- [ ] **Step 3: Implement `resolve_path`, `nearest_existing_dir`, `Entry`, and `list_dir` in `app/fs.py`**

Folders get `size=None`. Files get `st_size`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_fs.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/fs.py tests/test_fs.py
git commit -m "feat: add path resolution and directory listing"
```

---

### Task 3: Filename cleaning and saving files (`fs.py`)

**Files:**
- Modify: `app/fs.py`
- Modify: `tests/test_fs.py`

**Interfaces:**
- Consumes: nothing beyond Task 2's module.
- Produces: `clean_filename(raw: str | None) -> str`. Returns the text after the last `/` or `\`. Raises `ValueError("invalid filename")` if the result is empty, `.` or `..`, or contains `"\x00"`.
- Produces: `ensure_dir(path: Path, create: bool) -> None`. If the path is missing and `create` is true, runs `mkdir(parents=True, exist_ok=True)`. If it is missing and `create` is false, raises `FileNotFoundError`. If it exists but is not a folder, raises `NotADirectoryError`.
- Produces: the dataclass `FileResult(name: str, status: str)`, where `status` is one of the exact strings from Global Constraints.
- Produces: `save_file(storage, target_dir: Path, overwrite: bool) -> FileResult`. `storage` is anything with `.filename` and `.save(dst: str)`, such as Werkzeug's `FileStorage`. This function never raises. A `ValueError` from `clean_filename` or an `OSError` from saving becomes `failed: <message>`. `name` is the cleaned filename, or the raw one if cleaning failed (`""` if it was `None`). If the destination exists and `overwrite` is false, returns `skipped (exists)`. If the destination is a folder, returns `failed: is a directory` whatever `overwrite` is.

- [ ] **Step 1: Write the failing tests**

Use a `FakeStorage(filename, data: bytes)` stand-in whose `.save(dst)` writes `data` to `dst`.

```python
@pytest.mark.parametrize("raw,expected", [
    ("a.txt", "a.txt"), ("my file.txt", "my file.txt"), ("../../etc/x", "x"),
    ("a/b", "b"), (r"C:\Users\me\a b.txt", "a b.txt"),
])
def test_clean_filename_cases(raw, expected): ...

@pytest.mark.parametrize("raw", [None, "", ".", "..", "dir/", "a\x00b"])
def test_clean_filename_rejects(raw):
    with pytest.raises(ValueError): clean_filename(raw)

def test_ensure_dir_creates_parents(tmp_path): ...       # tmp/a/b exists after create=True
def test_ensure_dir_missing_no_create(tmp_path): ...     # FileNotFoundError
def test_ensure_dir_on_file(tmp_path): ...               # NotADirectoryError even with create=True

def test_save_file_saved(tmp_path):
    r = save_file(FakeStorage("a.txt", b"hi"), tmp_path, overwrite=False)
    assert r == FileResult("a.txt", "saved") and (tmp_path / "a.txt").read_bytes() == b"hi"

def test_save_file_skips_existing(tmp_path):    # content unchanged, status "skipped (exists)"
def test_save_file_overwrites(tmp_path):        # content replaced, status "saved"
def test_save_file_traversal_stays_in_dir(tmp_path):
    # filename "../evil.txt" -> written to tmp_path/"evil.txt", nothing in tmp_path.parent
def test_save_file_invalid_name(tmp_path):      # filename ".." -> status startswith "failed: "
def test_save_file_onto_directory_fails(tmp_path):
    (tmp_path / "d").mkdir()
    r = save_file(FakeStorage("d", b"x"), tmp_path, overwrite=True)
    assert r.status == "failed: is a directory"
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/pytest tests/test_fs.py -v`
Expected: the new tests fail with an `ImportError`.

- [ ] **Step 3: Implement `clean_filename`, `ensure_dir`, `FileResult`, and `save_file`**

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/pytest -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/fs.py tests/test_fs.py
git commit -m "feat: add filename cleaning and file saving"
```

---

### Task 4: Browse page (`/`, `/browse`, template)

**Files:**
- Modify: `app/routes.py`
- Create: `app/templates/browse.html`
- Create: `tests/test_routes.py`

**Interfaces:**
- Consumes: `resolve_path`, `nearest_existing_dir`, `list_dir`, `Entry` (Task 2).
- Produces: the route `main.index` (`GET /`), which redirects (302) to `/browse?path=/`.
- Produces: the route `main.browse` (`GET /browse?path=`). It always returns 200. When the path is missing or not a folder, it flashes `"Not a directory: <path>"` with the category `error` and lists `nearest_existing_dir`. When the listing raises an `OSError`, it flashes `"Cannot read <path>: <strerror>"` and renders with an empty listing.
- Produces: template context `path: Path`, `crumbs: list[tuple[str, str]]` as (label, path) pairs from `/` down to `path`, and `entries: list[Entry]`.
- The template contains: a breadcrumb of links; a GET form with the path text box (`name="path"`); flashed messages with categories; a table where folders link to `/browse?path=<child>` and files show size and modified time (`-` when `None`); and the upload form `POST /upload`, `enctype="multipart/form-data"`, with a hidden `path`, `<input type="file" name="files" multiple>`, checkboxes `create_dirs` and `overwrite`, and a submit button. Inline CSS only, with no external assets. Jinja autoescaping stays on, so names are never passed through `|safe`.

- [ ] **Step 1: Write the failing tests**

```python
def test_index_redirects(client):
    r = client.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/browse?path=/")

def test_browse_lists_entries(client, tmp_path):
    # mkdir sub, write f.txt; GET /browse?path=<tmp_path>
    # assert 200, b"sub" and b"f.txt" in body, b'name="files"' in body, b"multipart/form-data" in body

def test_browse_missing_falls_back(client, tmp_path):
    r = client.get(f"/browse?path={tmp_path}/nope/deeper")
    assert r.status_code == 200 and b"Not a directory" in r.data
    # tmp_path's own children are listed

def test_browse_escapes_names(client, tmp_path):
    (tmp_path / "<script>.txt").write_text("x")
    r = client.get(f"/browse?path={tmp_path}")
    assert b"<script>.txt" not in r.data and b"&lt;script&gt;.txt" in r.data

def test_browse_breadcrumbs(client, tmp_path):
    # every ancestor of tmp_path appears as a /browse?path=... link (URL-encoded per url_for)
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/pytest tests/test_routes.py -v`
Expected: the tests fail with 404s.

- [ ] **Step 3: Implement the routes and `browse.html`**

Build links with `url_for("main.browse", path=str(p))`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/pytest -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/routes.py app/templates tests/test_routes.py
git commit -m "feat: add directory browse page"
```

---

### Task 5: Upload endpoint and size-limit handling

**Files:**
- Modify: `app/routes.py`
- Modify: `tests/test_routes.py`

**Interfaces:**
- Consumes: `resolve_path`, `ensure_dir`, `save_file`, `FileResult` (Tasks 2–3).
- Produces: the route `main.upload` (`POST /upload`). It reads `path`, `request.files.getlist("files")` (ignoring parts with an empty filename), and the checkboxes `create_dirs` and `overwrite`, which are true when present. It always redirects (302) to `/browse?path=<resolved target>`.
  - If no files were sent, it flashes `"No files selected"` (category `error`).
  - If `ensure_dir` raises `FileNotFoundError`, it flashes `"Directory does not exist: <path> (tick 'Create folder' to create it)"` (`error`).
  - If `ensure_dir` raises `NotADirectoryError`, it flashes `"Not a directory: <path>"` (`error`). It flashes other `OSError`s as `"Cannot use <path>: <strerror>"` (`error`).
  - Otherwise it flashes one message per file, `"<name>: <status>"`, with category `ok` when the status is `saved` and `error` otherwise.
- Produces: an error handler for `RequestEntityTooLarge` (413). It flashes `"Upload exceeds the <N> MB limit"` (`error`) and redirects to `/`. It cannot read the form, so it can't know the target path.

- [ ] **Step 1: Write the failing tests**

Post with `data={"path": str(dir), "files": [(io.BytesIO(b"..."), "name")], ...}` and `content_type="multipart/form-data"`. Read flashes by following the redirect (`follow_redirects=True`) and checking the body.

```python
def test_upload_saves_multiple(client, tmp_path):      # a.txt, b c.txt saved; both "saved" in body
def test_upload_skips_existing(client, tmp_path):      # existing content unchanged; "skipped (exists)"
def test_upload_overwrite(client, tmp_path):           # overwrite=on -> content replaced
def test_upload_missing_dir_no_create(client, tmp_path):
    # path=tmp/new -> "Directory does not exist", tmp/new not created
def test_upload_create_dirs(client, tmp_path):         # path=tmp/new/deep, create_dirs=on -> file saved
def test_upload_target_is_file(client, tmp_path):
    # path=<existing file>, create_dirs=on -> "Not a directory", nothing written
def test_upload_no_files(client, tmp_path):            # "No files selected"
def test_upload_redirects_to_target(client, tmp_path):
    # without follow_redirects: 302, Location contains /browse?path=
def test_upload_too_large(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    client = create_app({"TESTING": True}).test_client()
    # post 2 MiB, follow_redirects=True -> 200 and b"exceeds the 1 MB limit" in body
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/pytest tests/test_routes.py -v`
Expected: the new tests fail (405 or 404).

- [ ] **Step 3: Implement `upload` and the 413 handler in `app/routes.py`**

Register the handler with `bp.app_errorhandler(RequestEntityTooLarge)`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/pytest -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/routes.py tests/test_routes.py
git commit -m "feat: add file upload endpoint"
```

---

### Task 6: Run script, README, manual acceptance, merge

**Files:**
- Create: `run.sh` (mode 755), `README.md`

**Interfaces:**
- Consumes: `create_app` (Task 1).

- [ ] **Step 1: Write `run.sh`**

It does `cd` into its own folder and runs the `exec` gunicorn line from the File Structure table, passing through `SECRET_KEY` and `MAX_UPLOAD_MB` if they are set. Run `chmod +x run.sh`.

- [ ] **Step 2: Write `README.md`**

Cover:
- Setup: `apt install python3.14-venv`, `python3 -m venv .venv`, `.venv/bin/pip install -e '.[dev]'`
- Running: `sudo ./run.sh`, then open `http://<server-ip>:8000`. Stop with Ctrl+C. Run tests with `.venv/bin/pytest`.
- Environment variables: `SECRET_KEY`, `MAX_UPLOAD_MB`.
- Security warning: no login plus root means anyone who can reach port 8000 controls the server.
- Optional firewall: `sudo ufw allow from <your-ip> to any port 8000 proto tcp` (with `deny 8000` if ufw's default allows).
- Git workflow: GitHub flow.

- [ ] **Step 3: Run the full test suite**

Run: `.venv/bin/pytest -v`
Expected: all tests pass, with 0 failures.

- [ ] **Step 4: Smoke test as root**

Start `sudo ./run.sh` in the background, then run `curl -s -o /dev/null -w '%{http_code}' http://<server-ip>:8000/browse?path=/`. Expected: `200`.

Upload to a directory outside `/home`:

```bash
curl -s -L -F path=/opt/fu-test -F create_dirs=on -F files=@README.md http://<server-ip>:8000/upload | grep -o 'README.md: saved'
```

Then check that `/opt/fu-test/README.md` exists and is owned by root. Clean up with `sudo rm -rf /opt/fu-test` and stop the server.

- [ ] **Step 5: Commit**

```bash
git add run.sh README.md
git commit -m "docs: add run script and readme"
```

- [ ] **Step 6: Ask the operator to do the browser check**

The operator opens `http://<server-ip>:8000` from their own machine and uploads a file. Wait for their confirmation.

- [ ] **Step 7: Merge into `main` (GitHub flow; no remote yet)**

```bash
git switch main && git merge --no-ff feat/file-upload-app -m "Merge branch 'feat/file-upload-app'" && git branch -d feat/file-upload-app
```

Expected: `git log --oneline --graph` shows the merge commit, and `.venv/bin/pytest` still passes on `main`.
