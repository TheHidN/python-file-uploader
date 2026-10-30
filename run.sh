#!/usr/bin/env bash
# Start the uploader on 0.0.0.0:8000. Run as root (sudo ./run.sh) so any directory is writable.
# Optional env: SECRET_KEY, MAX_UPLOAD_MB. Stop with Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")"
# One key shared by all workers; a per-worker random key breaks the flash-message cookie.
export SECRET_KEY="${SECRET_KEY:-$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')}"
# Hostnames the app answers to (blocks DNS rebinding): this box's IPs plus localhost.
export ALLOWED_HOSTS="${ALLOWED_HOSTS:-$(hostname -I | tr ' ' ','),localhost,127.0.0.1}"
# Spool uploads to disk, not /tmp (tmpfs, i.e. RAM, on this box).
export TMPDIR="${TMPDIR:-/var/tmp}"
# gthread workers keep heartbeating during long uploads; sync workers get killed after 30s.
exec .venv/bin/gunicorn -b 0.0.0.0:8000 -w 2 -k gthread --threads 4 --access-logfile - "app:create_app()"
