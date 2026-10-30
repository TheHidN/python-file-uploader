# File Uploader

A small Flask web app for browsing this server's folders and uploading files into any of them.
It is the first piece of a larger project.

> **Security warning:** there is no login, and the app runs as **root**. Anyone who can reach
> port 8000 can write any file on this server, which amounts to full control of it.
> Keep it on a trusted network, and see [Restricting access](#restricting-access-optional).

## Setup

```bash
sudo apt install python3.14-venv
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Running

```bash
sudo ./run.sh
```

Then open `http://<server-ip>:8000` in a browser, using this server's LAN address (`hostname -I` shows it). Stop the server with Ctrl+C. Gunicorn logs requests to the terminal.

`sudo` resets the environment, so pass any settings on the command line:

```bash
sudo MAX_UPLOAD_MB=500 ./run.sh
```

| Variable | Default | Purpose |
|---|---|---|
| `BIND` | `0.0.0.0` (all interfaces) | Address to listen on, e.g. one LAN address or `127.0.0.1`. |
| `PORT` | `8000` | Port to listen on. |
| `SECRET_KEY` | random per start | Signs the session cookie that carries status messages. |
| `MAX_UPLOAD_MB` | unset (no limit) | Rejects uploads larger than this many MB. |
| `ALLOWED_HOSTS` | this server's IPs, `localhost`, `127.0.0.1` | Comma-separated host names the app answers to. Add a DNS name here if you use one. |

Uploads are spooled to `/var/tmp` (on disk) while they arrive, then moved into place, so a failed
upload never damages an existing file. Uploads from other websites are refused (403), so a page
you visit can't make your browser upload files here.

## Using it

- Click through folders, or type a path in the box and press **Go**.
- Choose one or more files and press **Upload**. They go into the folder you are viewing.
- **Create folder if missing:** creates the target folder, including any missing parents.
- **Overwrite existing:** replaces files that already exist. Otherwise they are skipped.
- Each file is reported as `saved`, `skipped (exists)`, or `failed: <reason>`.

## Tests

```bash
.venv/bin/pytest
```

## Restricting access (optional)

To allow only your workstation to reach the app (replace `<your-ip>`):

```bash
sudo ufw allow from <your-ip> to any port 8000 proto tcp
sudo ufw deny 8000/tcp
sudo ufw enable   # only if ufw is not already active; make sure SSH is allowed first: sudo ufw allow OpenSSH
```

## Git workflow

GitHub flow: `main` is always releasable. All work happens on short-lived feature branches
(`feat/...`, `fix/...`, `docs/...`) that merge into `main` through pull requests. Commit messages
follow [Conventional Commits](https://www.conventionalcommits.org/).
