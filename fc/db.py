"""The SQLite file: connections, schema, and migration from the single-user
format. Stores build on this; nothing here knows about HTTP.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 2
LOCAL_USERNAME = "you"

# AUTOINCREMENT so an id is never handed out twice: a session cookie left over
# from a deleted account must not open a newer account with the same id.
_USERS = """
CREATE TABLE users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    google_sub  TEXT UNIQUE,
    username    TEXT UNIQUE,
    email       TEXT,
    name        TEXT NOT NULL,
    picture_url TEXT,
    session_epoch INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
)"""

_FLIGHTS = """
CREATE TABLE flights (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date          TEXT NOT NULL,
    origin        TEXT NOT NULL,
    dest          TEXT NOT NULL,
    airline       TEXT NOT NULL DEFAULT '',
    flight_number TEXT NOT NULL DEFAULT '',
    aircraft      TEXT NOT NULL DEFAULT '',
    seat          TEXT NOT NULL DEFAULT '',
    notes         TEXT NOT NULL DEFAULT '',
    distance_km   REAL NOT NULL,
    created_at    TEXT NOT NULL
)"""

_REQUESTS = """
CREATE TABLE mate_requests (
    from_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status     TEXT NOT NULL CHECK (status IN ('pending', 'declined', 'withdrawn')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (from_id, to_id),
    CHECK (from_id != to_id)
)"""

_MATES = """
CREATE TABLE mates (
    user_lo    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_hi    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_lo, user_hi),
    CHECK (user_lo < user_hi)
)"""

_LEGACY_COLUMNS = ("id, date, origin, dest, airline, flight_number, aircraft,"
                   " seat, notes, distance_km, created_at")


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def ensure_local_user(db: sqlite3.Connection) -> int:
    """Id of the local user, inserting it if missing. The caller commits."""
    row = db.execute(
        "SELECT id FROM users WHERE username = ? AND google_sub IS NULL",
        (LOCAL_USERNAME,)).fetchone()
    if row:
        return row["id"]
    return db.execute(
        "INSERT INTO users (username, name, created_at) VALUES (?, 'You', ?)",
        (LOCAL_USERNAME, datetime.now(UTC).isoformat())).lastrowid


def _version(db: sqlite3.Connection) -> int:
    return db.execute("PRAGMA user_version").fetchone()[0]


def _make_private(path: Path) -> None:
    """The database holds email addresses: owner-readable only."""
    if path.exists() and (path.stat().st_mode & 0o777) != 0o600:
        os.chmod(path, 0o600)


def init(path: Path) -> None:
    """Create the schema, or bring an older database up to it. A database
    already at the current version is left untouched.

    Version 0 is either empty or the single-user format (a bare flights
    table). Version 1 lacks users.session_epoch."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with closing(connect(path)) as db:
        version = _version(db)
        if version >= SCHEMA_VERSION:
            _make_private(path)
            return
        legacy = version == 0 and db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table'"
            " AND name = 'flights'").fetchone() is not None

    if legacy:
        # Keep the pre-migration file. Never overwrite an earlier backup.
        backup = path.with_name(path.name + ".pre-users.bak")
        if not backup.exists():
            shutil.copy2(path, backup)

    with closing(connect(path)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            version = _version(db)      # another process may have got here first
            if version == 0:
                _create(db, legacy)
            elif version == 1:
                db.execute("ALTER TABLE users ADD COLUMN"
                           " session_epoch INTEGER NOT NULL DEFAULT 0")
            if version < SCHEMA_VERSION:
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            db.commit()
        except BaseException:
            db.rollback()
            raise
    _make_private(path)


def _create(db: sqlite3.Connection, legacy: bool) -> None:
    for ddl in (_USERS, _REQUESTS, _MATES):
        db.execute(ddl)
    if legacy:
        owner = ensure_local_user(db)
        db.execute("ALTER TABLE flights RENAME TO flights_legacy")
        db.execute(_FLIGHTS)
        db.execute(
            f"INSERT INTO flights ({_LEGACY_COLUMNS}, user_id)"
            f" SELECT {_LEGACY_COLUMNS}, ? FROM flights_legacy", (owner,))
        db.execute("DROP TABLE flights_legacy")
    else:
        db.execute(_FLIGHTS)
    db.execute("CREATE INDEX flights_user_date ON flights (user_id, date)")
