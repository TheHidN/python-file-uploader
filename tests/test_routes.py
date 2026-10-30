import io

from flask import url_for
from markupsafe import escape

from app import create_app


def browse_link(app, path) -> bytes:
    with app.test_request_context():
        return f'href="{escape(url_for("main.browse", path=str(path)))}"'.encode()


def test_index_redirects(client):
    r = client.get("/")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/browse?path=/")


def test_browse_lists_entries(app, client, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "f.txt").write_text("hello")
    r = client.get("/browse", query_string={"path": str(tmp_path)})
    assert r.status_code == 200
    assert b"sub" in r.data and b"f.txt" in r.data
    assert browse_link(app, tmp_path / "sub") in r.data
    assert b'name="files"' in r.data and b"multipart/form-data" in r.data
    assert f'name="path" value="{tmp_path}"'.encode() in r.data


def test_browse_missing_falls_back(client, tmp_path):
    (tmp_path / "child").mkdir()
    r = client.get("/browse", query_string={"path": f"{tmp_path}/nope/deeper"})
    assert r.status_code == 200
    assert b"Not a directory" in r.data
    assert b"child" in r.data


def test_browse_escapes_names(client, tmp_path):
    (tmp_path / "<script>.txt").write_text("x")
    r = client.get("/browse", query_string={"path": str(tmp_path)})
    assert b"<script>.txt" not in r.data
    assert b"&lt;script&gt;.txt" in r.data


def test_browse_breadcrumbs(app, client, tmp_path):
    r = client.get("/browse", query_string={"path": str(tmp_path)})
    for p in [tmp_path, *tmp_path.parents]:
        assert browse_link(app, p) in r.data


def test_browse_unreadable_dir(client, tmp_path, monkeypatch):
    import app.routes

    def boom(path):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(app.routes, "list_dir", boom)
    r = client.get("/browse", query_string={"path": str(tmp_path)})
    assert r.status_code == 200
    assert b"Cannot read" in r.data and b"Permission denied" in r.data


def _upload(client, path, files, follow=True, **flags):
    data = {"path": str(path), "files": [(io.BytesIO(body), name) for name, body in files]}
    data.update({k: "on" for k, v in flags.items() if v})
    return client.post("/upload", data=data, content_type="multipart/form-data",
                       follow_redirects=follow)


def test_upload_saves_multiple(client, tmp_path):
    r = _upload(client, tmp_path, [("a.txt", b"A"), ("b c.txt", b"BC")])
    assert r.status_code == 200
    assert (tmp_path / "a.txt").read_bytes() == b"A"
    assert (tmp_path / "b c.txt").read_bytes() == b"BC"
    assert b"a.txt: saved" in r.data and b"b c.txt: saved" in r.data


def test_upload_skips_existing(client, tmp_path):
    (tmp_path / "a.txt").write_bytes(b"old")
    r = _upload(client, tmp_path, [("a.txt", b"new")])
    assert (tmp_path / "a.txt").read_bytes() == b"old"
    assert b"a.txt: skipped (exists)" in r.data


def test_upload_overwrite(client, tmp_path):
    (tmp_path / "a.txt").write_bytes(b"old")
    r = _upload(client, tmp_path, [("a.txt", b"new")], overwrite=True)
    assert (tmp_path / "a.txt").read_bytes() == b"new"
    assert b"a.txt: saved" in r.data


def test_upload_missing_dir_no_create(client, tmp_path):
    r = _upload(client, tmp_path / "new", [("a.txt", b"A")])
    assert b"Directory does not exist" in r.data
    assert not (tmp_path / "new").exists()


def test_upload_create_dirs(client, tmp_path):
    r = _upload(client, tmp_path / "new" / "deep", [("a.txt", b"A")], create_dirs=True)
    assert (tmp_path / "new" / "deep" / "a.txt").read_bytes() == b"A"
    assert b"a.txt: saved" in r.data


def test_upload_target_is_file(client, tmp_path):
    f = tmp_path / "f"
    f.write_text("x")
    r = _upload(client, f, [("a.txt", b"A")], create_dirs=True)
    assert b"Not a directory" in r.data
    assert f.read_text() == "x" and sorted(p.name for p in tmp_path.iterdir()) == ["f"]


def test_upload_no_files(client, tmp_path):
    r = client.post("/upload", data={"path": str(tmp_path)}, follow_redirects=True)
    assert b"No files selected" in r.data


def test_upload_empty_file_part_counts_as_none(client, tmp_path):
    r = _upload(client, tmp_path, [("", b"")])
    assert b"No files selected" in r.data


def test_upload_escapes_names_in_flash(client, tmp_path):
    r = _upload(client, tmp_path, [("<b>x.txt", b"A")])
    assert b"<b>x.txt" not in r.data and b"&lt;b&gt;x.txt: saved" in r.data


def test_upload_redirects_to_target(app, client, tmp_path):
    r = _upload(client, tmp_path, [("a.txt", b"A")], follow=False)
    assert r.status_code == 302
    with app.test_request_context():
        assert r.headers["Location"].endswith(url_for("main.browse", path=str(tmp_path)))


def test_upload_too_large(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    client = create_app({"TESTING": True}).test_client()
    r = _upload(client, tmp_path, [("big.bin", b"x" * (2 * 1024 * 1024))])
    assert r.status_code == 200
    assert b"exceeds the 1 MB limit" in r.data
    assert not (tmp_path / "big.bin").exists()


def test_upload_rejects_cross_origin(client, tmp_path):
    r = client.post("/upload", data={"path": str(tmp_path), "files": [(io.BytesIO(b"A"), "a.txt")]},
                    headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert not (tmp_path / "a.txt").exists()


def test_upload_rejects_cross_site_fetch(client, tmp_path):
    r = client.post("/upload", data={"path": str(tmp_path), "files": [(io.BytesIO(b"A"), "a.txt")]},
                    headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert not (tmp_path / "a.txt").exists()


def test_upload_allows_same_origin(client, tmp_path):
    client.post("/upload", data={"path": str(tmp_path), "files": [(io.BytesIO(b"A"), "a.txt")]},
                headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"})
    assert (tmp_path / "a.txt").exists()


def test_allowed_hosts_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "192.0.2.10, localhost")
    client = create_app({"TESTING": True}).test_client()
    assert client.get("/browse", headers={"Host": "192.0.2.10:8000"}).status_code == 200
    assert client.get("/browse", headers={"Host": "rebind.evil.example"}).status_code == 400


def test_upload_disk_full_while_parsing_is_flashed(client, tmp_path, monkeypatch):
    from flask import Request

    def full(self):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Request, "_load_form_data", full)
    r = client.post("/upload", data={"path": str(tmp_path)}, follow_redirects=True)
    assert r.status_code == 200
    assert b"Upload failed: No space left on device" in r.data


JSON = {"Accept": "application/json"}


def test_browse_has_drop_zone(client, tmp_path):
    r = client.get("/browse", query_string={"path": str(tmp_path)})
    assert b'id="dropzone"' in r.data and b'id="progress"' in r.data


def test_upload_json_returns_redirect_and_keeps_flash(app, client, tmp_path):
    r = client.post("/upload", headers=JSON,
                    data={"path": str(tmp_path), "files": [(io.BytesIO(b"A"), "a.txt")]})
    assert r.status_code == 200
    with app.test_request_context():
        assert r.json == {"redirect": url_for("main.browse", path=str(tmp_path))}
    assert (tmp_path / "a.txt").read_bytes() == b"A"
    assert b"a.txt: saved" in client.get(r.json["redirect"]).data


def test_upload_json_error_also_returns_redirect(client, tmp_path):
    r = client.post("/upload", headers=JSON, data={"path": str(tmp_path)})
    assert r.status_code == 200 and "redirect" in r.json
    assert b"No files selected" in client.get(r.json["redirect"]).data


def test_upload_json_too_large(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    client = create_app({"TESTING": True}).test_client()
    r = client.post("/upload", headers=JSON,
                    data={"path": str(tmp_path), "files": [(io.BytesIO(b"x" * (2 << 20)), "big.bin")]})
    assert r.status_code == 413 and r.json["redirect"].startswith("/")
    assert b"exceeds the 1 MB limit" in client.get(r.json["redirect"], follow_redirects=True).data
