# File Uploader — Design Spec

- **Date:** 2026-10-30
- **Status:** Approved in conversation; pending written-spec review
- **Host:** Linux server, LAN IP `<server-ip>`

## Purpose

A small Python web app for uploading files from a browser into any directory
on this server. It is temporary in its current form but is the first piece of
a larger project, so it is built to be folded in later (Flask blueprint,
filesystem logic isolated from HTTP).

## Decisions

| Topic | Decision |
|---|---|
| Users | Single operator (the owner). |
| Authentication | None. |
| Process user | Root, so any directory is writable. |
| Framework | Flask, served by Gunicorn. |
| Bind address | `0.0.0.0:8000` → `http://<server-ip>:8000`. |
| Startup | Manual: `sudo ./run.sh`, stopped with Ctrl+C. Starting at boot (systemd) is deferred to a later feature branch. |
| Directory selection | Server-side folder browser starting at `/`, plus a path box to jump directly. |
| Location | `~/file-uploader` (may move once the home-directory layout is reorganized). |

**Accepted risk:** with no login and root privileges, anyone who can reach
port 8000 can write any file on the server, which amounts to full control of it.
The owner accepted this. The README documents an optional `ufw` rule that
restricts port 8000 to a single client IP; it is not applied automatically.

## Architecture

```
file-uploader/
├── app/
│   ├── __init__.py      # create_app() factory, loads config
│   ├── routes.py        # HTTP endpoints (Flask blueprint)
│   ├── fs.py            # filesystem logic; no Flask imports
│   └── templates/
│       └── browse.html  # breadcrumb, folder listing, upload form, messages
├── tests/
│   ├── test_fs.py
│   └── test_routes.py
├── docs/superpowers/specs/
├── run.sh               # starts gunicorn on 0.0.0.0:8000
├── pyproject.toml       # deps: flask, gunicorn; dev: pytest
├── .gitignore
└── README.md
```

- `fs.py` holds all disk access and is testable on its own against temporary
  directories.
- `routes.py` is a thin layer: parse the request, call `fs.py`, render a
  template or redirect.
- Dependencies are installed in a virtualenv at `.venv/` inside the project.
  `run.sh` uses `.venv/bin/gunicorn`.

## Endpoints

| Method | Path | Behavior |
|---|---|---|
| GET | `/` | Redirect to `/browse?path=/`. |
| GET | `/browse?path=<dir>` | Show the directory: breadcrumb, folders first and then files (name, size, modified time), a path box, the upload form, and any flash messages. |
| POST | `/upload` | Form fields: `path` (target dir), `files` (one or more), `create_dirs` (checkbox), `overwrite` (checkbox). Saves the files, flashes a per-file result, and redirects to `/browse?path=<target>`. |

## Behavior

### Paths
- The `path` value is made absolute and normalized before use. Symlinks are
  allowed and followed.
- If `path` does not exist or is not a directory, the browse page shows an
  error message. When this happens, the browse page falls back to listing the
  nearest existing parent directory.

### Listing
- Entries are sorted case-insensitively, folders first and then files.
- An entry that cannot be read (`stat` fails, for example a broken symlink) is
  still listed, without size or modified time.
- If the directory itself cannot be read (`PermissionError` or `OSError`), the
  page shows an error message instead of a listing.

### Uploading
- Each upload is streamed to disk through Werkzeug's file storage, so large
  files are not held in memory.
- **Filename handling:** only the final path component is kept (the part
  after the last `/` or `\`). Names that are empty, `.` or `..`, or that
  contain a NUL byte are rejected for that file. Spaces and other ordinary
  characters are kept as they are; `secure_filename` is not used.
- **Missing target directory:** if `create_dirs` is ticked, the directory is
  created along with any missing parents (`mkdir -p`). Otherwise the whole
  upload fails with an error message.
- **Existing file:** if `overwrite` is ticked, the file is replaced.
  Otherwise that file is skipped.
- **Per-file results:** each file is reported as `saved`, `skipped (exists)`,
  or `failed: <reason>`. One file failing does not stop the others.
- If no files are selected, the page shows an error message.
- **Size limit:** none by default. Setting the optional environment variable
  `MAX_UPLOAD_MB` sets Flask's `MAX_CONTENT_LENGTH`. An upload over the limit
  shows an error message and does not crash.

### Errors
- Every expected failure is reported as a flash message on the page, and the
  user never sees a stack trace.
- Gunicorn writes its access and error logs to the terminal.
- Flask's `SECRET_KEY`, which flash messages need, is read from the
  environment variable `SECRET_KEY`. If it is not set, a random key is
  generated when the app starts.

## Testing

Tests are written first (TDD) and run with pytest.

- `test_fs.py` covers: listing order and contents, unreadable entries, saving
  a file, skipping vs. overwriting, creating directories, rejecting traversal
  in filenames (`../x`, `a/b`, `..`), and non-existent or non-directory paths.
- `test_routes.py` uses Flask's test client against a temporary directory and
  covers: the `/` redirect, the browse page rendering, a successful upload, a
  skip on an existing file, the error for a missing directory, the error for no
  files, and the error for an invalid path.
- **Manual acceptance:** start with `sudo ./run.sh`, open
  `http://<server-ip>:8000` from another machine, browse to a directory outside
  `/home`, and upload a file there.

## Git workflow

The project uses GitHub flow.

1. `main` gets one direct commit, the initial one: this spec.
2. Implementation happens on `feat/file-upload-app`, using Conventional
   Commits.
3. The branch is merged into `main` with `--no-ff` and then deleted. Once a
   GitHub remote exists, merges go through pull requests.

## Out of scope (for now)

- Authentication or TLS.
- Starting at boot (systemd unit). Planned as `feat/systemd-service`.
- Downloading, deleting, renaming, or moving files on the server.
- Upload progress bars and drag-and-drop.
