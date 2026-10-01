"""Settings, read once from environment variables.

Two auth modes: `local`, where every request acts as the local user, and
`google`, where people sign in.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_DATA_DIR = Path.home() / ".wingmates"
DEFAULT_BASE_URL = "http://localhost:8817"
GOOGLE_CLIENT_FILE = "google-client.json"
AUTH_MODES = ("local", "google")


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name) or ""
    if raw == "":
        return default
    if raw not in ("0", "1"):
        raise ValueError(f"{name} must be 0 or 1, got {raw!r}")
    return raw == "1"


def normalize_base_url(raw: str) -> str:
    """The address people use, in one canonical spelling: lowercase host, no
    default port, no trailing slash. The app compares request hosts against
    this, so two spellings of one address must not differ."""
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        parts = port = None
    if (parts is None or parts.scheme not in ("http", "https")
            or not parts.hostname or parts.username or parts.password
            or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise ValueError(
            "WINGMATES_BASE_URL must look like https://host or "
            f"http://host:port, got {raw!r}")
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    default = 443 if parts.scheme == "https" else 80
    return f"{parts.scheme}://{host}" + (
        f":{port}" if port and port != default else "")


def _base_url(env: Mapping[str, str]) -> str:
    """The address people use. On Render the service's own hostname is known,
    so nothing needs setting until a custom domain is added."""
    explicit = env.get("WINGMATES_BASE_URL")
    if explicit:
        return explicit
    render_host = env.get("RENDER_EXTERNAL_HOSTNAME")
    return f"https://{render_host}" if render_host else DEFAULT_BASE_URL


def _google_client(env: Mapping[str, str], data_dir: Path) -> tuple[str, str]:
    """Client id and secret: from the environment, or from the file Google's
    console downloads, saved in the data directory."""
    cid, secret = env.get("GOOGLE_CLIENT_ID"), env.get("GOOGLE_CLIENT_SECRET")
    if cid and secret:
        return cid, secret
    path = data_dir / GOOGLE_CLIENT_FILE
    try:
        web = json.loads(path.read_text())["web"]
        cid, secret = web["client_id"], web["client_secret"]
    except (OSError, ValueError, KeyError, TypeError):
        cid = secret = None
    if not (isinstance(cid, str) and cid and isinstance(secret, str) and secret):
        raise ValueError(
            "Google sign-in needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, "
            f"or the client file from Google saved as {path}")
    return cid, secret


@dataclass(frozen=True)
class Config:
    auth: str = "local"
    live: bool = True
    dev_users: bool = False
    data_dir: Path = DEFAULT_DATA_DIR
    base_url: str = DEFAULT_BASE_URL
    # Secrets stay out of repr so they cannot end up in a log line.
    secret_key: str | None = field(default=None, repr=False)
    google_client_id: str | None = None
    google_client_secret: str | None = field(default=None, repr=False)

    def __post_init__(self):
        # Frozen, so set through object: every Config holds the canonical form.
        object.__setattr__(self, "base_url", normalize_base_url(self.base_url))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "flights.db"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        auth = env.get("WINGMATES_AUTH") or "local"
        if auth not in AUTH_MODES:
            raise ValueError(
                f"WINGMATES_AUTH must be one of {', '.join(AUTH_MODES)}; got {auth!r}")
        local = auth == "local"
        data_dir = Path(env.get("WINGMATES_DATA_DIR") or DEFAULT_DATA_DIR).expanduser()
        cid = secret = None
        if not local:
            cid, secret = _google_client(env, data_dir)
        return cls(
            auth=auth,
            live=_flag(env, "WINGMATES_LIVE", local),
            # Switching users without signing in must never work on a real site.
            dev_users=_flag(env, "WINGMATES_DEV_USERS", False) and local,
            data_dir=data_dir,
            base_url=_base_url(env),
            secret_key=env.get("SECRET_KEY") or None,
            google_client_id=cid,
            google_client_secret=secret,
        )
