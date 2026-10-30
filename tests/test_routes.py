from flask import url_for
from markupsafe import escape


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
