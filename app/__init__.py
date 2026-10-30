import os
import secrets

from flask import Flask


def create_app(config: dict | None = None) -> Flask:
    """Build the app; settings come from the environment, then `config` overrides."""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    max_mb = os.environ.get("MAX_UPLOAD_MB")
    app.config["MAX_CONTENT_LENGTH"] = int(max_mb) * 1024 * 1024 if max_mb else None
    hosts = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
    app.config["TRUSTED_HOSTS"] = hosts or None  # guards against DNS rebinding
    if config:
        app.config.update(config)

    from app.routes import bp

    app.register_blueprint(bp)
    return app
