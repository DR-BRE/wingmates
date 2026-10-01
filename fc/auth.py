"""Sign-in plumbing. The only module that knows about Google.

`GoogleSignIn` is deliberately tiny: begin() sends the person to Google and
finish() returns who came back. The web layer depends on those two methods
only, so tests swap in a fake and never touch the network.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from authlib.common.errors import AuthlibBaseError
from authlib.integrations.flask_client import OAuth

GOOGLE_METADATA = "https://accounts.google.com/.well-known/openid-configuration"
SCOPES = "openid email profile"


def safe_next(value) -> str:
    """Where to send someone after sign-in. Only a path on this site is
    honoured; anything else could bounce them to another site."""
    if (isinstance(value, str) and value.startswith("/")
            and not value.startswith("//") and "\\" not in value
            and not any(ord(c) < 32 for c in value)):
        return value
    return "/"


def persistent_key(data_dir: Path) -> str:
    """The key that signs session cookies, kept in the data directory so
    sign-ins survive a restart. Created on first use, owner-readable only."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "secret_key"
    if path.exists():
        key = path.read_text().strip()
        if key:
            return key
        path.unlink()
    key = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key)
    return key


class GoogleSignIn:
    def __init__(self, app, client_id: str, client_secret: str):
        self._oauth = OAuth(app)
        self._oauth.register(
            name="google",
            server_metadata_url=GOOGLE_METADATA,
            client_id=client_id,
            client_secret=client_secret,
            client_kwargs={"scope": SCOPES},
        )

    def begin(self, redirect_uri: str):
        return self._oauth.google.authorize_redirect(redirect_uri)

    def finish(self) -> dict | None:
        """Who signed in, or None if they cancelled or the response did not
        verify. Authlib checks the state and nonce and validates the ID token."""
        try:
            token = self._oauth.google.authorize_access_token()
        except AuthlibBaseError:
            return None
        info = token.get("userinfo") or {}
        if not info.get("sub"):
            return None
        return {"sub": info["sub"], "email": info.get("email"),
                "name": info.get("name"), "picture_url": info.get("picture")}
