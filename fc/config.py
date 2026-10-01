"""Settings, read once from environment variables.

Only `local` auth exists so far: every request acts as the local user. Google
sign-in adds a second mode later.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_DIR = Path.home() / ".wingmates"
DEFAULT_BASE_URL = "http://localhost:8817"


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name) or ""
    if raw == "":
        return default
    if raw not in ("0", "1"):
        raise ValueError(f"{name} must be 0 or 1, got {raw!r}")
    return raw == "1"


@dataclass(frozen=True)
class Config:
    auth: str = "local"
    live: bool = True
    dev_users: bool = False
    data_dir: Path = DEFAULT_DATA_DIR
    base_url: str = DEFAULT_BASE_URL
    secret_key: str | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "flights.db"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        auth = env.get("WINGMATES_AUTH") or "local"
        if auth != "local":
            raise ValueError(
                f"WINGMATES_AUTH must be 'local', got {auth!r}; "
                "Google sign-in is not built yet")
        return cls(
            auth=auth,
            live=_flag(env, "WINGMATES_LIVE", True),
            dev_users=_flag(env, "WINGMATES_DEV_USERS", False),
            data_dir=Path(env.get("WINGMATES_DATA_DIR") or DEFAULT_DATA_DIR).expanduser(),
            base_url=(env.get("WINGMATES_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            secret_key=env.get("SECRET_KEY") or None,
        )
