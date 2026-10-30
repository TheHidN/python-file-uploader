from app import create_app


def test_secret_key_from_env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "abc")
    assert create_app().config["SECRET_KEY"] == "abc"


def test_secret_key_random_when_unset(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    k1 = create_app().config["SECRET_KEY"]
    k2 = create_app().config["SECRET_KEY"]
    assert len(k1) == 64 and k1 != k2


def test_no_upload_limit_by_default(monkeypatch):
    monkeypatch.delenv("MAX_UPLOAD_MB", raising=False)
    assert create_app().config["MAX_CONTENT_LENGTH"] is None


def test_upload_limit_from_env(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "5")
    assert create_app().config["MAX_CONTENT_LENGTH"] == 5 * 1024 * 1024
