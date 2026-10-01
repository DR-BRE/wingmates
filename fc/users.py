"""User records and username rules. Knows nothing about HTTP or Google."""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from .db import LOCAL_USERNAME, connect, ensure_local_user, init

USERNAME_RE = re.compile(r"[a-z0-9_]{3,20}")
RESERVED = frozenset({"admin", "wingmates", "support", LOCAL_USERNAME})

# The only user fields that ever leave this module. Email is stored but never
# returned, so no caller can pass it on by accident.
PUBLIC_FIELDS = ("id", "username", "name", "picture_url")


def normalize_username(raw) -> str:
    """How people type usernames: stray spaces, a leading @, capitals."""
    return str(raw or "").strip().lstrip("@").strip().lower()


def validate_username(raw) -> str:
    name = normalize_username(raw)
    if not USERNAME_RE.fullmatch(name):
        raise ValueError(
            "a username is 3 to 20 characters: letters, digits and underscore")
    if name in RESERVED:
        raise ValueError(f"the username {name!r} is reserved")
    return name


class Users:
    def __init__(self, path: Path):
        self.path = path
        init(path)

    @staticmethod
    def _public(row: sqlite3.Row | None) -> dict | None:
        return {k: row[k] for k in PUBLIC_FIELDS} if row else None

    def create(self, name: str, username: str, *, google_sub: str | None = None,
               email: str | None = None, picture_url: str | None = None) -> dict:
        username = validate_username(username)
        name = str(name or "").strip() or username
        try:
            with closing(connect(self.path)) as db, db:
                uid = db.execute(
                    "INSERT INTO users (google_sub, username, email, name,"
                    " picture_url, created_at) VALUES (?,?,?,?,?,?)",
                    (google_sub, username, email, name, picture_url,
                     datetime.now(UTC).isoformat())).lastrowid
        except sqlite3.IntegrityError:
            raise ValueError(f"the username {username!r} is taken") from None
        return self.get(uid)

    def upsert_google(self, sub: str, email: str | None, name: str | None,
                      picture_url: str | None) -> dict:
        """The account for this Google identity, created on first sign-in and
        refreshed on every later one. Keyed on `sub`, which never changes, so
        a new email address does not make a second account."""
        name = (name or "").strip() or (email or "").split("@")[0] or "Wingmate"
        with closing(connect(self.path)) as db, db:
            row = db.execute("SELECT id FROM users WHERE google_sub = ?",
                             (sub,)).fetchone()
            if row:
                uid = row["id"]
                db.execute("UPDATE users SET email = ?, name = ?, picture_url = ?"
                           " WHERE id = ?", (email, name, picture_url, uid))
            else:
                uid = db.execute(
                    "INSERT INTO users (google_sub, email, name, picture_url,"
                    " created_at) VALUES (?,?,?,?,?)",
                    (sub, email, name, picture_url,
                     datetime.now(UTC).isoformat())).lastrowid
        return self.get(uid)

    def set_username(self, user_id: int, raw: str) -> dict:
        """Choose a username. Allowed once: the UPDATE only matches a user
        that has none, so a second attempt changes nothing."""
        username = validate_username(raw)
        try:
            with closing(connect(self.path)) as db, db:
                changed = db.execute(
                    "UPDATE users SET username = ? WHERE id = ?"
                    " AND username IS NULL", (username, user_id)).rowcount
        except sqlite3.IntegrityError:
            raise ValueError(f"the username {username!r} is taken") from None
        if not changed:
            raise ValueError("you already have a username")
        return self.get(user_id)

    def get(self, user_id: int) -> dict | None:
        with closing(connect(self.path)) as db:
            return self._public(db.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    def session_epoch(self, user_id: int) -> int | None:
        with closing(connect(self.path)) as db:
            row = db.execute("SELECT session_epoch FROM users WHERE id = ?",
                             (user_id,)).fetchone()
        return row["session_epoch"] if row else None

    def for_session(self, user_id: int, epoch) -> dict | None:
        """The user a session cookie names, if that cookie is still good.
        Signing out raises the account's epoch, which retires every cookie
        issued before it, including copies."""
        if isinstance(epoch, bool) or not isinstance(epoch, int):
            return None
        with closing(connect(self.path)) as db:
            return self._public(db.execute(
                "SELECT * FROM users WHERE id = ? AND session_epoch = ?",
                (user_id, epoch)).fetchone())

    def end_sessions(self, user_id: int) -> None:
        with closing(connect(self.path)) as db, db:
            db.execute("UPDATE users SET session_epoch = session_epoch + 1"
                       " WHERE id = ?", (user_id,))

    def by_username(self, raw: str) -> dict | None:
        name = normalize_username(raw)
        if not name:
            return None
        with closing(connect(self.path)) as db:
            return self._public(db.execute(
                "SELECT * FROM users WHERE username = ?", (name,)).fetchone())

    def ensure_local(self) -> dict:
        with closing(connect(self.path)) as db, db:
            uid = ensure_local_user(db)
        return self.get(uid)

    def delete(self, user_id: int) -> bool:
        """Remove the user. Their flights, requests and mate pairs go with
        them through the schema's ON DELETE CASCADE."""
        with closing(connect(self.path)) as db, db:
            return db.execute("DELETE FROM users WHERE id = ?",
                              (user_id,)).rowcount > 0
