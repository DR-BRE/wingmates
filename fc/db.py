"""The SQLite file: connections, schema, and migration from the single-user
format. Stores build on this; nothing here knows about HTTP.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from .turso import Turso, TursoConnection

SCHEMA_VERSION = 3
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

_GMAIL_LINKS = """
CREATE TABLE gmail_links (
    user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    refresh_token TEXT NOT NULL,
    email         TEXT NOT NULL DEFAULT '',
    connected_at  TEXT NOT NULL,
    last_scan_at  TEXT
)"""

_LEGACY_COLUMNS = ("id, date, origin, dest, airline, flight_number, aircraft,"
                   " seat, notes, distance_km, created_at")


def connect(database):
    """A connection to a SQLite file, or to Turso. Both offer execute(),
    executemany(), commit(), rollback(), close() and rows that take a column
    name, which is all the stores use."""
    if isinstance(database, Turso):
        return TursoConnection(database)
    db = sqlite3.connect(database)
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


def _if_missing(ddl: str) -> str:
    return ddl.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)


def _init_turso(database: Turso) -> None:
    """Create the tables on Turso if they are not there. A Turso database
    starts empty, so there is nothing older to migrate from. One request."""
    connect(database).batch(
        [_if_missing(ddl).strip()
         for ddl in (_USERS, _FLIGHTS, _REQUESTS, _MATES, _GMAIL_LINKS)]
        + ["CREATE INDEX IF NOT EXISTS flights_user_date"
           " ON flights (user_id, date)"])


def readable(database) -> bool:
    """Can the users table be read? For the health check. A missing SQLite
    file is opened read-only, so asking does not create one."""
    try:
        if isinstance(database, Turso):
            connect(database).execute("SELECT 1 FROM users LIMIT 1")
        else:
            uri = Path(database).resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as db:
                db.execute("SELECT 1 FROM users LIMIT 1")
    except sqlite3.Error:
        return False
    return True


def _make_private(path: Path) -> None:
    """The database holds email addresses: owner-readable only."""
    try:
        if path.exists() and (path.stat().st_mode & 0o777) != 0o600:
            os.chmod(path, 0o600)
    except OSError as e:
        # Some mounted disks refuse chmod. Tightening permissions is a
        # precaution; failing to must not stop the server starting.
        logging.getLogger(__name__).warning(
            "could not restrict %s to its owner: %s", path, type(e).__name__)


def init(path) -> None:
    """Create the schema, or bring an older database up to it. A database
    already at the current version is left untouched.

    Version 0 is either empty or the single-user format (a bare flights
    table). Version 1 lacks users.session_epoch. Version 2 lacks
    gmail_links."""
    if isinstance(path, Turso):
        return _init_turso(path)
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
            else:
                # Cumulative, not a chain: a version 1 database upgrading
                # straight to 3 must pick up every step on the way.
                if version < 2:
                    db.execute("ALTER TABLE users ADD COLUMN"
                               " session_epoch INTEGER NOT NULL DEFAULT 0")
                if version < 3:
                    db.execute(_GMAIL_LINKS)
            if version < SCHEMA_VERSION:
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            db.commit()
        except BaseException:
            db.rollback()
            raise
    _make_private(path)


def _create(db: sqlite3.Connection, legacy: bool) -> None:
    for ddl in (_USERS, _REQUESTS, _MATES, _GMAIL_LINKS):
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
