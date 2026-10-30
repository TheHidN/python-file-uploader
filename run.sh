#!/usr/bin/env bash
# Start the uploader on 0.0.0.0:8000. Run as root (sudo ./run.sh) so any directory is writable.
# Optional env: SECRET_KEY, MAX_UPLOAD_MB. Stop with Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")"
# One key shared by all workers; a per-worker random key breaks the flash-message cookie.
export SECRET_KEY="${SECRET_KEY:-$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')}"
exec .venv/bin/gunicorn -b 0.0.0.0:8000 -w 2 --access-logfile - "app:create_app()"
