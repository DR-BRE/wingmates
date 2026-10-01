# Social Core (Local) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Wingmates multi-user on localhost: users with usernames, flights scoped to a user, username lookup, mate requests, and a Social tab that compares wingspans and draws a mate's routes.

**Architecture:** Flask replaces the stdlib HTTP server. Three stores (`users`, `history`, `mates`) share one SQLite file and know nothing about HTTP; `webapp.py` is the only module that touches requests. There is no real sign-in yet: every request acts as the local user `@you`, and a dev-only control switches between made-up users so the Social tab can be exercised.

**Tech Stack:** Python 3.11+, Flask 3.1, SQLite (stdlib `sqlite3`), `unittest`, vanilla JS, three.js r160, Leaflet 1.9.

**Spec:** `docs/superpowers/specs/2026-10-01-mates-and-wingspans-design.md`

This plan is build step 1 of the spec. **Deferred to later plans:** Google sign-in, sessions for real accounts, the choose-a-username page, the 401 and 409 rules, account deletion in the UI, profile pictures (plan 2); Dockerfile, gunicorn, `/healthz`, host setup (plan 3).

## Global Constraints

- Python 3.11 or newer. The only new dependency in this plan is `Flask>=3.1,<4`.
- All tests are offline: temp directories, no network, no real `~/.wingmates`.
- Run tests with `.venv/bin/python -m unittest discover -s tests -t .`
- Usernames: 3 to 20 characters from `a-z`, `0-9`, `_`. Input is trimmed, a leading `@` dropped, and lowercased before checking. Reserved: `admin`, `wingmates`, `support`, `you`.
- The local user has username `you`, name `You`, and `google_sub` NULL.
- User ids are never reused (`AUTOINCREMENT`).
- A mate request has status `pending`, `declined` or `withdrawn`. At most 20 requests per sender may be in `pending` or `declined`.
- What anyone may see of another person by lookup: `id`, `username`, `name`, `picture_url`, `relation`. What a mate may also see: `stats` with exactly `flights`, `distance_mi`, `distance_km`, `airports`, `countries`; and distinct routes whose airports carry exactly `iata`, `name`, `city`, `country`, `lat`, `lon`.
- Never sent to anyone but the owner: `email`, flight `date`, `airline`, `flight_number`, `aircraft`, `seat`, `notes`, flight `id`, or how often a route was flown.
- Wingspan is `distance_mi`. Times around the Earth is `distance_mi / 24901`, one decimal place.
- Every `POST` must carry `Content-Type: application/json` and an `Origin` whose host and port equal the request's `Host`; otherwise 403.
- Errors are JSON `{"error": "<message>"}` with a 4xx or 5xx status.
- Colours: the user's routes `#5fd0dd`, a mate's routes `#f08a6b`.
- End every commit message with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

Each of these has a test in the task named.

1. **A username typed the way people type them** (`@Brett `, mixed case). Expected: found, same as `brett`. Task 3 and Task 7.
2. **A POST whose body is not a JSON object** (an array, or broken JSON). Expected: 400 with a message, never a 500. Task 6.
3. **A dev session pointing at a user that has since been deleted.** Expected: the request acts as `@you`, no 500. Task 6.
4. **A stored flight whose airport code is no longer in the airport table.** Expected: stats still compute and the mate's route list skips that flight. Task 5.
5. **Starting the app twice on a database in today's format.** Expected: the second start changes nothing, the backup is not overwritten, and no second local user appears. Task 2.

## File Structure

| File | Responsibility |
|---|---|
| `requirements.txt` (new) | Pinned dependencies. |
| `fc/config.py` (new) | Reads environment settings into one `Config`. |
| `fc/db.py` (new) | SQLite connection, schema, migration from today's format. |
| `fc/users.py` (new) | User rows and username rules. |
| `fc/history.py` (modify) | Flights, reached only through `History.for_user(id)`. |
| `fc/mates.py` (new) | Requests, mate pairs, and the only code that describes one user to another. |
| `fc/webapp.py` (new) | Flask app factory and every route. |
| `fc/server.py` (delete) | Replaced by `webapp.py`. |
| `run.py` (modify) | Starts Flask, and the tracker when Live is on. |
| `web/app.js` (modify) | Shared helpers, escaping, boot from `/api/me`, Live gating. |
| `web/history.js` (modify) | Tabs for three panes, keyed map route layers, Export link. |
| `web/social.js` (new) | Social tab. |
| `web/globe.js` (modify) | Two route layers. |
| `web/index.html`, `web/style.css` (modify) | Markup and styles for the above. |
| `tests/helpers.py` (new) | Shared airport fixture and store factory. |
| `tests/test_config.py`, `test_db.py`, `test_users.py`, `test_mates.py`, `test_webapp.py` (new) | One per module. |
| `tests/test_history.py` (modify) | Uses `for_user`; adds isolation and export. |

---

### Task 1: Branch, virtualenv and Config

**Files:**
- Create: `requirements.txt`, `fc/config.py`, `tests/test_config.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: `fc.config.Config` (frozen dataclass) with fields `auth: str`, `live: bool`, `dev_users: bool`, `data_dir: Path`, `base_url: str`, `secret_key: str | None`; property `db_path -> Path`; classmethod `from_env(env: Mapping[str, str] | None = None) -> Config`, raising `ValueError` on bad settings.

- [ ] **Step 1: Create the branch and the virtualenv**

Homebrew's Python refuses `pip install` outside a virtualenv, so the project gets its own.

```bash
cd ~/flighty-clone
git checkout -b social-core
git add docs/superpowers && git commit -m "Add social design spec and step-1 plan

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
printf 'Flask>=3.1,<4\n' > requirements.txt
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -c "import flask; print(flask.__version__)"
```

Expected: a version starting `3.1`.

- [ ] **Step 2: Ignore the virtualenv and the dev data folder**

Append to `.gitignore`:

```
.venv/
.devdata/
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_config.py`:

```python
"""Config tests: settings come from a mapping, never the real environment."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.config import Config


class TestConfig(unittest.TestCase):

    def test_defaults_are_local_with_live_on(self):
        c = Config.from_env({})
        self.assertEqual((c.auth, c.live, c.dev_users), ("local", True, False))
        self.assertEqual(c.db_path, Path.home() / ".wingmates" / "flights.db")
        self.assertEqual(c.base_url, "http://localhost:8817")
        self.assertIsNone(c.secret_key)

    def test_settings_are_read_from_the_mapping(self):
        c = Config.from_env({
            "WINGMATES_LIVE": "0", "WINGMATES_DEV_USERS": "1",
            "WINGMATES_DATA_DIR": "/tmp/wm", "SECRET_KEY": "s3",
            "WINGMATES_BASE_URL": "https://wingmates.example/"})
        self.assertEqual((c.live, c.dev_users), (False, True))
        self.assertEqual(c.db_path, Path("/tmp/wm/flights.db"))
        self.assertEqual(c.base_url, "https://wingmates.example")
        self.assertEqual(c.secret_key, "s3")

    def test_a_flag_that_is_not_0_or_1_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            Config.from_env({"WINGMATES_LIVE": "yes"})
        self.assertIn("WINGMATES_LIVE", str(cm.exception))

    def test_an_auth_mode_other_than_local_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            Config.from_env({"WINGMATES_AUTH": "google"})
        self.assertIn("WINGMATES_AUTH", str(cm.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 4: Run it and confirm it fails**

Run: `.venv/bin/python -m unittest tests.test_config -v`
Expected: `ModuleNotFoundError: No module named 'fc.config'`

- [ ] **Step 5: Implement**

Create `fc/config.py`:

```python
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
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: `OK`, 44 tests (40 existing plus 4).

- [ ] **Step 7: Commit**

```bash
git add .gitignore requirements.txt fc/config.py tests/test_config.py
git commit -m "Add Config and project virtualenv

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Database schema and migration

**Files:**
- Create: `fc/db.py`, `tests/test_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `fc.db.connect(path: Path) -> sqlite3.Connection` — rows are `sqlite3.Row`, foreign keys on.
  - `fc.db.init(path: Path) -> None` — creates or migrates the schema; safe to call repeatedly.
  - `fc.db.ensure_local_user(db: sqlite3.Connection) -> int` — id of the `you` user, inserting it if missing. Does not commit.
  - `fc.db.LOCAL_USERNAME = "you"`, `fc.db.SCHEMA_VERSION = 1`.
  - Tables `users`, `flights`, `mate_requests`, `mates` as in the spec.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_db.py`:

```python
"""Schema and migration tests. Offline: temp files only."""
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc import db

# The flights table exactly as the single-user app created it.
LEGACY = """
CREATE TABLE flights (
    id INTEGER PRIMARY KEY, date TEXT NOT NULL, origin TEXT NOT NULL,
    dest TEXT NOT NULL, airline TEXT NOT NULL DEFAULT '',
    flight_number TEXT NOT NULL DEFAULT '', aircraft TEXT NOT NULL DEFAULT '',
    seat TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
    distance_km REAL NOT NULL, created_at TEXT NOT NULL)"""


class DbCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "flights.db"
        self.backup = self.path.with_name("flights.db.pre-users.bak")

    def legacy(self):
        with closing(sqlite3.connect(self.path)) as raw, raw:
            raw.execute(LEGACY)
            raw.executemany(
                "INSERT INTO flights (date, origin, dest, airline, distance_km,"
                " created_at) VALUES (?,?,?,?,?,?)",
                [("2026-09-17", "SEA", "KEF", "Icelandair", 5811.0, "t1"),
                 ("2024-03-09", "ATL", "LHR", "", 6760.0, "t2")])

    def tables(self):
        with closing(db.connect(self.path)) as c:
            return {r["name"] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name NOT LIKE 'sqlite_%'")}


class TestFresh(DbCase):

    def test_creates_the_schema_without_a_backup(self):
        db.init(self.path)
        self.assertEqual(self.tables(),
                         {"users", "flights", "mate_requests", "mates"})
        self.assertFalse(self.backup.exists())
        with closing(db.connect(self.path)) as c:
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0],
                             db.SCHEMA_VERSION)

    def test_deleting_a_user_deletes_their_flights(self):
        db.init(self.path)
        with closing(db.connect(self.path)) as c, c:
            uid = db.ensure_local_user(c)
            c.execute("INSERT INTO flights (user_id, date, origin, dest,"
                      " distance_km, created_at) VALUES (?,?,?,?,?,?)",
                      (uid, "2024-01-01", "ATL", "JFK", 1200.0, "t"))
            c.execute("DELETE FROM users WHERE id = ?", (uid,))
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM flights").fetchone()[0], 0)

    def test_a_deleted_users_id_is_not_given_to_the_next_user(self):
        db.init(self.path)
        with closing(db.connect(self.path)) as c, c:
            first = db.ensure_local_user(c)
            c.execute("DELETE FROM users WHERE id = ?", (first,))
            self.assertNotEqual(db.ensure_local_user(c), first)

    def test_ensure_local_user_is_stable(self):
        db.init(self.path)
        with closing(db.connect(self.path)) as c, c:
            self.assertEqual(db.ensure_local_user(c), db.ensure_local_user(c))


class TestMigration(DbCase):

    def test_existing_flights_are_given_to_the_local_user(self):
        self.legacy()
        db.init(self.path)
        with closing(db.connect(self.path)) as c:
            users = c.execute("SELECT * FROM users").fetchall()
            flights = c.execute(
                "SELECT * FROM flights ORDER BY date").fetchall()
        self.assertEqual([(u["username"], u["name"], u["google_sub"])
                          for u in users], [("you", "You", None)])
        self.assertEqual([(f["origin"], f["dest"], f["airline"], f["user_id"])
                          for f in flights],
                         [("ATL", "LHR", "", users[0]["id"]),
                          ("SEA", "KEF", "Icelandair", users[0]["id"])])

    def test_the_old_file_is_kept_as_a_backup(self):
        self.legacy()
        db.init(self.path)
        with closing(sqlite3.connect(self.backup)) as raw:
            cols = [r[1] for r in raw.execute("PRAGMA table_info(flights)")]
            count = raw.execute("SELECT COUNT(*) FROM flights").fetchone()[0]
        self.assertNotIn("user_id", cols)
        self.assertEqual(count, 2)

    def test_starting_twice_changes_nothing(self):
        self.legacy()
        db.init(self.path)
        before = self.backup.read_bytes()
        db.init(self.path)
        with closing(db.connect(self.path)) as c:
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM flights").fetchone()[0], 2)
        self.assertEqual(self.backup.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_db -v`
Expected: `ImportError: cannot import name 'db' from 'fc'`

- [ ] **Step 3: Implement**

Create `fc/db.py`:

```python
"""The SQLite file: connections, schema, and migration from the single-user
format. Stores build on this; nothing here knows about HTTP.
"""
from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1
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


def init(path: Path) -> None:
    """Create the schema, or migrate a single-user database to it. A database
    already at the current version is left untouched."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as db:
        if _version(db) >= SCHEMA_VERSION:
            return
        legacy = db.execute(
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
            if _version(db) >= SCHEMA_VERSION:   # another process got here first
                db.rollback()
                return
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
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            db.commit()
        except BaseException:
            db.rollback()
            raise
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_db -v`
Expected: 7 tests, `OK`.

- [ ] **Step 5: Commit**

```bash
git add fc/db.py tests/test_db.py
git commit -m "Add database schema with migration from single-user format

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Users and usernames

**Files:**
- Create: `fc/users.py`, `tests/test_users.py`

**Interfaces:**
- Consumes: `fc.db.connect`, `fc.db.init`, `fc.db.ensure_local_user`, `fc.db.LOCAL_USERNAME`.
- Produces:
  - `fc.users.normalize_username(raw) -> str` — trims, drops a leading `@`, lowercases; no validation.
  - `fc.users.validate_username(raw) -> str` — normalizes, raises `ValueError` if malformed or reserved.
  - `class Users(path: Path)` with:
    - `create(name: str, username: str, *, google_sub=None, email=None, picture_url=None) -> dict` — raises `ValueError` if the username is invalid or taken.
    - `get(user_id: int) -> dict | None`
    - `by_username(raw: str) -> dict | None` — normalizes first.
    - `ensure_local() -> dict`
    - `delete(user_id: int) -> bool`
  - Every returned user dict has exactly the keys `id`, `username`, `name`, `picture_url`. Email never leaves this module.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_users.py`:

```python
"""User store tests. Offline: a temp database."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.users import Users, normalize_username, validate_username


class TestUsernameRules(unittest.TestCase):

    def test_input_is_trimmed_unprefixed_and_lowercased(self):
        self.assertEqual(normalize_username("  @Brett "), "brett")
        self.assertEqual(validate_username("@Brett_99"), "brett_99")
        self.assertEqual(normalize_username(None), "")

    def test_malformed_names_are_refused(self):
        for bad in ("ab", "a" * 21, "has space", "dash-ed", "émile", "", None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                validate_username(bad)

    def test_length_limits_are_inclusive(self):
        self.assertEqual(validate_username("abc"), "abc")
        self.assertEqual(validate_username("a" * 20), "a" * 20)

    def test_reserved_names_are_refused(self):
        for bad in ("admin", "Wingmates", "support", "you"):
            with self.assertRaises(ValueError) as cm:
                validate_username(bad)
            self.assertIn("reserved", str(cm.exception))


class UsersCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.users = Users(Path(tmp.name) / "flights.db")


class TestUsers(UsersCase):

    def test_create_returns_only_public_fields(self):
        u = self.users.create("Ann Lee", "Ann", email="ann@example.com")
        self.assertEqual(set(u), {"id", "username", "name", "picture_url"})
        self.assertEqual((u["username"], u["name"]), ("ann", "Ann Lee"))
        self.assertEqual(self.users.get(u["id"]), u)

    def test_a_taken_username_is_refused_whatever_its_case(self):
        self.users.create("Ann", "ann")
        with self.assertRaises(ValueError) as cm:
            self.users.create("Other", "ANN")
        self.assertIn("taken", str(cm.exception))

    def test_lookup_accepts_the_way_people_type_usernames(self):
        u = self.users.create("Brett", "brett")
        self.assertEqual(self.users.by_username("@Brett "), u)
        self.assertIsNone(self.users.by_username("bret"))
        self.assertIsNone(self.users.by_username(""))

    def test_local_user_is_created_once(self):
        a, b = self.users.ensure_local(), self.users.ensure_local()
        self.assertEqual(a, b)
        self.assertEqual((a["username"], a["name"]), ("you", "You"))

    def test_a_deleted_users_name_can_be_taken_again(self):
        u = self.users.create("Ann", "ann")
        self.assertTrue(self.users.delete(u["id"]))
        self.assertFalse(self.users.delete(u["id"]))
        self.assertIsNone(self.users.get(u["id"]))
        self.assertNotEqual(self.users.create("New Ann", "ann")["id"], u["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_users -v`
Expected: `ModuleNotFoundError: No module named 'fc.users'`

- [ ] **Step 3: Implement**

Create `fc/users.py`:

```python
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

    def get(self, user_id: int) -> dict | None:
        with closing(connect(self.path)) as db:
            return self._public(db.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

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
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_users -v`
Expected: 9 tests, `OK`.

- [ ] **Step 5: Commit**

```bash
git add fc/users.py tests/test_users.py
git commit -m "Add user store and username rules

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Flights scoped to a user, and CSV export

**Files:**
- Modify: `fc/history.py` (replace everything from `_SCHEMA = """` to the end of the file)
- Modify: `tests/test_history.py`

**Interfaces:**
- Consumes: `fc.db.connect`, `fc.db.init`; `fc.users.Users` (tests only).
- Produces:
  - `class History(airports: Airports | None = None, path: Path = DB_FILE)` with attributes `airports`, `path` and one method: `for_user(user_id: int) -> UserHistory`.
  - `class UserHistory` with attributes `airports`, `path`, `user_id` and methods `add(day, origin, dest, **extra) -> dict`, `update(flight_id, day, origin, dest, **extra) -> dict | None`, `delete(flight_id) -> bool`, `get(flight_id) -> dict | None`, `list() -> list[dict]`, `stats(flights=None) -> dict`, `snapshot() -> dict`, `import_csv(text) -> dict`, `export_csv() -> str`. Shapes are unchanged from today. Every one of them sees only `user_id`'s flights.
  - Module names kept: `OPTIONAL`, `TEMPLATE_COLUMNS`, `KM_PER_MILE`, `great_circle_km`, `template_csv`, `DB_FILE`.

There is no way to reach flights except through `for_user`, so no query can forget whose flights it is touching.

- [ ] **Step 1: Update the existing tests to the new entry point**

In `tests/test_history.py`, change the import line and `HistoryCase.setUp`:

```python
from fc.airports import Airports
from fc.history import History, great_circle_km, template_csv
from fc.users import Users
```

```python
class HistoryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        (d / "airports.csv").write_text(AIRPORTS_CSV)
        self.airports = Airports(d / "airports.csv")
        self.store = History(self.airports, d / "flights.db")
        self.users = Users(d / "flights.db")
        self.uid = self.users.create("Ann", "ann")["id"]
        self.h = self.store.for_user(self.uid)
```

In `test_survives_reopening_the_database`, replace the `again = ...` line with:

```python
        again = History(self.airports, self.h.path).for_user(self.uid)
```

- [ ] **Step 2: Add the new failing tests**

Add to `tests/test_history.py`, above the `if __name__` line:

```python
class TestIsolation(HistoryCase):

    def setUp(self):
        super().setUp()
        self.other = self.store.for_user(self.users.create("Bob", "bob")["id"])

    def test_each_user_sees_only_their_own_flights_and_stats(self):
        self.h.add("2024-03-09", "ATL", "LHR")
        self.other.add("2024-05-01", "ATL", "JFK")
        self.assertEqual([f["to"]["iata"] for f in self.h.list()], ["LHR"])
        self.assertEqual([f["to"]["iata"] for f in self.other.list()], ["JFK"])
        self.assertEqual(self.h.stats()["flights"], 1)
        self.assertEqual(self.other.snapshot()["stats"]["airports"], 2)

    def test_another_users_flight_looks_exactly_like_a_missing_one(self):
        f = self.h.add("2024-03-09", "ATL", "LHR")
        self.assertIsNone(self.other.get(f["id"]))
        self.assertIsNone(self.other.update(f["id"], "2024-03-10", "ATL", "JFK"))
        self.assertFalse(self.other.delete(f["id"]))
        self.assertEqual(self.h.get(f["id"])["to"]["iata"], "LHR")

    def test_import_duplicates_are_judged_per_user(self):
        text = "date,from,to\n2024-03-09,ATL,LHR\n"
        self.h.import_csv(text)
        self.assertEqual(self.other.import_csv(text)["added"], 1)
        self.assertEqual(self.h.import_csv(text)["skipped"], 1)

    def test_deleting_a_user_removes_their_flights_only(self):
        self.h.add("2024-03-09", "ATL", "LHR")
        self.other.add("2024-05-01", "ATL", "JFK")
        self.users.delete(self.uid)
        self.assertEqual(self.h.list(), [])
        self.assertEqual(len(self.other.list()), 1)


class TestExport(HistoryCase):

    def test_export_starts_with_the_template_header(self):
        self.assertEqual(self.h.export_csv(), template_csv())

    def test_export_imports_back_to_the_same_flights(self):
        self.h.add("2024-03-09", "ATL", "LHR", airline="Delta",
                   flight_number="DL30", aircraft="A333", seat="34A",
                   notes='window, "left" side')
        self.h.add("2020-01-01", "ATL", "JFK")
        other = self.store.for_user(self.users.create("Bob", "bob")["id"])
        self.assertEqual(other.import_csv(self.h.export_csv()),
                         {"added": 2, "skipped": 0, "errors": []})
        strip = lambda fs: [{k: v for k, v in f.items() if k != "id"} for f in fs]
        self.assertEqual(strip(other.list()), strip(self.h.list()))
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_history -v`
Expected: errors with `AttributeError: 'History' object has no attribute 'for_user'`

- [ ] **Step 4: Implement**

In `fc/history.py`, change the imports at the top to:

```python
import csv
import io
import math
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

from .airports import Airports
from .db import connect, init
```

Then replace everything from the line `_SCHEMA = """` to the end of the file with:

```python
def great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class History:
    """The flight store. Flights are reached only through for_user(), so no
    query can forget whose flights it is touching."""

    def __init__(self, airports: Airports | None = None, path: Path = DB_FILE):
        self.airports = airports or Airports()
        self.path = path
        init(path)

    def for_user(self, user_id: int) -> "UserHistory":
        return UserHistory(self, user_id)


class UserHistory:
    """One user's flights. Every statement here filters on user_id."""

    def __init__(self, history: History, user_id: int):
        self.airports = history.airports
        self.path = history.path
        self.user_id = user_id

    # ----------------------------------------------------------------- writes
    def _validate(self, day: str, origin: str, dest: str) -> tuple:
        try:
            d = date.fromisoformat((day or "").strip())
        except ValueError:
            raise ValueError(f"date must be YYYY-MM-DD, got {day!r}") from None
        o, t = self.airports.get(origin), self.airports.get(dest)
        if o is None:
            raise ValueError(f"unknown airport code {origin!r}")
        if t is None:
            raise ValueError(f"unknown airport code {dest!r}")
        if o.iata == t.iata:
            raise ValueError("origin and destination are the same airport")
        return d, o, t

    def _insert(self, db, d, o, t, extra: dict) -> int:
        km = great_circle_km(o.lat, o.lon, t.lat, t.lon)
        cur = db.execute(
            "INSERT INTO flights (user_id, date, origin, dest, airline,"
            " flight_number, aircraft, seat, notes, distance_km, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (self.user_id, d.isoformat(), o.iata, t.iata,
             *[(extra.get(k) or "").strip() for k in OPTIONAL],
             km, datetime.now(UTC).isoformat()))
        return cur.lastrowid

    def add(self, day: str, origin: str, dest: str, **extra) -> dict:
        d, o, t = self._validate(day, origin, dest)
        with closing(connect(self.path)) as db, db:
            fid = self._insert(db, d, o, t, extra)
        return self.get(fid)

    def update(self, flight_id: int, day: str, origin: str, dest: str,
               **extra) -> dict | None:
        """Replace a flight's fields. Distance is recomputed from the airports.
        Returns None if this user has no such flight."""
        d, o, t = self._validate(day, origin, dest)
        km = great_circle_km(o.lat, o.lon, t.lat, t.lon)
        with closing(connect(self.path)) as db, db:
            changed = db.execute(
                "UPDATE flights SET date=?, origin=?, dest=?, airline=?,"
                " flight_number=?, aircraft=?, seat=?, notes=?, distance_km=?"
                " WHERE id=? AND user_id=?",
                (d.isoformat(), o.iata, t.iata,
                 *[(extra.get(k) or "").strip() for k in OPTIONAL],
                 km, flight_id, self.user_id)).rowcount
        return self.get(flight_id) if changed else None

    def delete(self, flight_id: int) -> bool:
        with closing(connect(self.path)) as db, db:
            return db.execute(
                "DELETE FROM flights WHERE id = ? AND user_id = ?",
                (flight_id, self.user_id)).rowcount > 0

    def import_csv(self, text: str) -> dict:
        """Add every valid row; report the rest by line number. A row that
        matches one of this user's flights (date, route, flight number) is
        skipped, so importing the same file twice is harmless."""
        reader = csv.reader(io.StringIO(text.lstrip("﻿")))
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("the file is empty") from None
        cols = [_ALIASES.get(h.strip().lower()) for h in header]
        missing = [c for c in ("date", "from", "to") if c not in cols]
        if missing:
            raise ValueError(
                "missing column(s): " + ", ".join(missing)
                + ". The first row must be a header like: "
                + ",".join(TEMPLATE_COLUMNS))

        added = skipped = 0
        errors: list[dict] = []
        with closing(connect(self.path)) as db, db:
            seen = {(r["date"], r["origin"], r["dest"], r["flight_number"].upper())
                    for r in db.execute(
                        "SELECT * FROM flights WHERE user_id = ?",
                        (self.user_id,))}
            for line, raw in enumerate(reader, start=2):
                if not any(c.strip() for c in raw):
                    continue
                row = {c: v.strip() for c, v in zip(cols, raw) if c}
                try:
                    d, o, t = self._validate(row.get("date", ""),
                                             row.get("from", ""), row.get("to", ""))
                except ValueError as e:
                    errors.append({"line": line, "error": str(e)})
                    continue
                key = (d.isoformat(), o.iata, t.iata,
                       row.get("flight_number", "").upper())
                if key in seen:
                    skipped += 1
                    continue
                seen.add(key)
                self._insert(db, d, o, t, row)
                added += 1
        return {"added": added, "skipped": skipped, "errors": errors}

    # ------------------------------------------------------------------ reads
    def _row(self, r: sqlite3.Row) -> dict:
        o, t = self.airports.get(r["origin"]), self.airports.get(r["dest"])
        return {
            "id": r["id"], "date": r["date"],
            "from": o.to_json() if o else {"iata": r["origin"]},
            "to": t.to_json() if t else {"iata": r["dest"]},
            **{k: r[k] for k in OPTIONAL},
            "distance_km": round(r["distance_km"], 1),
            "distance_mi": round(r["distance_km"] / KM_PER_MILE, 1),
        }

    def get(self, flight_id: int) -> dict | None:
        with closing(connect(self.path)) as db:
            r = db.execute(
                "SELECT * FROM flights WHERE id = ? AND user_id = ?",
                (flight_id, self.user_id)).fetchone()
        return self._row(r) if r else None

    def list(self) -> list[dict]:
        with closing(connect(self.path)) as db:
            rows = db.execute(
                "SELECT * FROM flights WHERE user_id = ?"
                " ORDER BY date DESC, id DESC", (self.user_id,)).fetchall()
        return [self._row(r) for r in rows]

    def stats(self, flights: list[dict] | None = None) -> dict:
        flights = self.list() if flights is None else flights
        codes = {f[end]["iata"] for f in flights for end in ("from", "to")}
        countries = {f[end].get("country") for f in flights
                     for end in ("from", "to")} - {None, ""}
        km = sum(f["distance_km"] for f in flights)
        longest = max(flights, key=lambda f: f["distance_km"], default=None)
        return {
            "flights": len(flights),
            "distance_km": round(km),
            "distance_mi": round(km / KM_PER_MILE),
            "airports": len(codes),
            "countries": len(countries),
            "longest": ({"from": longest["from"]["iata"],
                         "to": longest["to"]["iata"],
                         "distance_mi": round(longest["distance_mi"])}
                        if longest else None),
        }

    def snapshot(self) -> dict:
        flights = self.list()
        return {"flights": flights, "stats": self.stats(flights)}

    def export_csv(self) -> str:
        """This user's flights in the import template's columns, oldest first."""
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(TEMPLATE_COLUMNS)
        with closing(connect(self.path)) as db:
            for r in db.execute(
                    "SELECT * FROM flights WHERE user_id = ? ORDER BY date, id",
                    (self.user_id,)):
                w.writerow([r["date"], r["origin"], r["dest"],
                            *[r[k] for k in OPTIONAL]])
        return out.getvalue()


def template_csv() -> str:
    return ",".join(TEMPLATE_COLUMNS) + "\n"
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_history -v`
Expected: 24 tests, `OK`.

`fc/server.py` still calls the old `History` methods and is now broken. That is expected: nothing imports it in the tests, and Task 6 deletes it.

- [ ] **Step 6: Commit**

```bash
git add fc/history.py tests/test_history.py
git commit -m "Scope flight history to a user and add CSV export

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Requests, mates and what a mate may see

**Files:**
- Create: `fc/mates.py`, `tests/helpers.py`, `tests/test_mates.py`

**Interfaces:**
- Consumes: `Users.get`, `Users.by_username`; `History.for_user(id).stats()` and `.list()`; `fc.db.connect`.
- Produces `class Mates(users: Users, history: History)`:
  - `card(viewer_id: int, username: str) -> dict | None` — `{id, username, name, picture_url, relation}`; `relation` is `self`, `mate`, `requested`, `incoming` or `none`.
  - `request(from_id: int, username: str) -> dict` — the same card after the request. Raises `LookupError` if the username is unknown; `ValueError` for your own username, an existing mate, or the limit.
  - `accept(user_id, other_id) -> bool`, `decline(user_id, other_id) -> bool`, `cancel(user_id, other_id) -> bool`, `remove(user_id, other_id) -> bool` — `True` if something changed.
  - `social(user_id: int) -> dict` — `{"me": person+stats, "mates": [person+stats, by wingspan], "incoming": [person], "outgoing": [person]}` where person is `{id, username, name, picture_url}`.
  - `routes(viewer_id: int, mate_id: int) -> list[dict] | None` — `None` unless the two are mates; otherwise `[{"from": airport, "to": airport}]`.
  - `MAX_REQUESTS = 20`.
- Also produces `tests/helpers.py`: `AIRPORTS_CSV` and `stores(case) -> (dir, airports, history, users)`.

- [ ] **Step 1: Write the shared test helper**

Create `tests/helpers.py`:

```python
"""Shared fixtures for store and web tests. Offline."""
import tempfile
from pathlib import Path

from fc.airports import Airports
from fc.history import History
from fc.users import Users

AIRPORTS_CSV = """iata,icao,name,city,country,lat,lon,size
ATL,KATL,Hartsfield Jackson Atlanta International Airport,Atlanta,US,33.6367,-84.4281,3
JFK,KJFK,John F. Kennedy International Airport,New York,US,40.6394,-73.7793,3
LHR,EGLL,London Heathrow Airport,London,GB,51.4707,-0.4599,3
NRT,RJAA,Narita International Airport,Narita,JP,35.7686,140.3887,3
"""


def stores(case):
    """A temp data directory with an airport table, a History and a Users,
    cleaned up when the test case finishes."""
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    d = Path(tmp.name)
    (d / "airports.csv").write_text(AIRPORTS_CSV)
    airports = Airports(d / "airports.csv")
    return d, airports, History(airports, d / "flights.db"), Users(d / "flights.db")
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_mates.py`:

```python
"""Mates store tests: requests, pairs, and what one user may see of another."""
import sys
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.db import connect
from fc.mates import MAX_REQUESTS, Mates
from tests.helpers import stores

PERSON = {"id", "username", "name", "picture_url"}
PRIVATE = {"email", "date", "airline", "flight_number", "aircraft", "seat",
           "notes", "google_sub", "count", "times"}


def keys(obj):
    """Every dict key anywhere inside obj."""
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in keys(v)}
    return set()


class MatesCase(unittest.TestCase):
    def setUp(self):
        self.dir, self.airports, self.history, self.users = stores(self)
        self.mates = Mates(self.users, self.history)
        self.ann = self.users.create("Ann", "ann")["id"]
        self.bob = self.users.create("Bob", "bob")["id"]

    def rel(self, viewer, username):
        return self.mates.card(viewer, username)["relation"]

    def befriend(self, a, a_name, b, b_name):
        self.mates.request(a, b_name)
        self.assertTrue(self.mates.accept(b, a))


class TestCard(MatesCase):

    def test_card_has_only_the_lookup_fields(self):
        self.history.for_user(self.bob).add("2024-03-09", "ATL", "LHR")
        card = self.mates.card(self.ann, "bob")
        self.assertEqual(set(card), PERSON | {"relation"})
        self.assertEqual(card["relation"], "none")

    def test_lookup_is_exact_but_forgiving_about_typing(self):
        self.assertEqual(self.mates.card(self.ann, "@Bob ")["id"], self.bob)
        self.assertIsNone(self.mates.card(self.ann, "bo"))
        self.assertIsNone(self.mates.card(self.ann, "nobody"))

    def test_relation_in_each_state(self):
        self.assertEqual(self.rel(self.ann, "ann"), "self")
        self.assertEqual(self.rel(self.ann, "bob"), "none")
        self.mates.request(self.ann, "bob")
        self.assertEqual(self.rel(self.ann, "bob"), "requested")
        self.assertEqual(self.rel(self.bob, "ann"), "incoming")
        self.mates.accept(self.bob, self.ann)
        self.assertEqual(self.rel(self.ann, "bob"), "mate")
        self.assertEqual(self.rel(self.bob, "ann"), "mate")


class TestRequests(MatesCase):

    def test_request_then_accept_is_visible_from_both_sides(self):
        self.assertEqual(self.mates.request(self.ann, "bob")["relation"],
                         "requested")
        s = self.mates.social(self.bob)
        self.assertEqual([p["username"] for p in s["incoming"]], ["ann"])
        self.assertEqual(self.mates.social(self.ann)["outgoing"][0]["username"],
                         "bob")
        self.assertTrue(self.mates.accept(self.bob, self.ann))
        for uid, other in ((self.ann, "bob"), (self.bob, "ann")):
            s = self.mates.social(uid)
            self.assertEqual([m["username"] for m in s["mates"]], [other])
            self.assertEqual((s["incoming"], s["outgoing"]), ([], []))

    def test_only_the_recipient_can_accept(self):
        self.mates.request(self.ann, "bob")
        self.assertFalse(self.mates.accept(self.ann, self.bob))
        self.assertFalse(self.mates.accept(self.bob, 999))
        self.assertEqual(self.rel(self.ann, "bob"), "requested")

    def test_crossing_requests_make_mates_at_once(self):
        self.mates.request(self.ann, "bob")
        self.assertEqual(self.mates.request(self.bob, "ann")["relation"], "mate")
        self.assertEqual(self.mates.social(self.ann)["outgoing"], [])

    def test_asking_twice_changes_nothing(self):
        self.mates.request(self.ann, "bob")
        self.mates.request(self.ann, "bob")
        self.assertEqual(len(self.mates.social(self.bob)["incoming"]), 1)

    def test_decline_is_silent_and_blocks_a_second_request(self):
        self.mates.request(self.ann, "bob")
        self.assertTrue(self.mates.decline(self.bob, self.ann))
        self.assertFalse(self.mates.decline(self.bob, self.ann))
        self.assertEqual(self.mates.social(self.bob)["incoming"], [])
        # Ann is not told: it still reads as requested, before and after retrying.
        self.assertEqual(self.rel(self.ann, "bob"), "requested")
        self.assertEqual(self.mates.request(self.ann, "bob")["relation"],
                         "requested")
        self.assertEqual(self.mates.social(self.bob)["incoming"], [])
        self.assertEqual(self.rel(self.bob, "ann"), "none")

    def test_the_decliner_can_still_add_them_later(self):
        self.mates.request(self.ann, "bob")
        self.mates.decline(self.bob, self.ann)
        self.assertEqual(self.mates.request(self.bob, "ann")["relation"], "mate")

    def test_cancel_of_a_pending_request_allows_a_new_one(self):
        self.mates.request(self.ann, "bob")
        self.assertTrue(self.mates.cancel(self.ann, self.bob))
        self.assertFalse(self.mates.cancel(self.ann, self.bob))
        self.assertEqual(self.mates.social(self.bob)["incoming"], [])
        self.mates.request(self.ann, "bob")
        self.assertEqual(len(self.mates.social(self.bob)["incoming"]), 1)

    def test_cancel_of_a_declined_request_keeps_the_block(self):
        self.mates.request(self.ann, "bob")
        self.mates.decline(self.bob, self.ann)
        self.assertTrue(self.mates.cancel(self.ann, self.bob))
        self.assertEqual(self.rel(self.ann, "bob"), "none")
        self.assertEqual(self.mates.social(self.ann)["outgoing"], [])
        self.assertEqual(self.mates.request(self.ann, "bob")["relation"],
                         "requested")
        self.assertEqual(self.mates.social(self.bob)["incoming"], [])

    def test_after_a_withdrawn_request_the_other_side_must_ask_normally(self):
        self.mates.request(self.ann, "bob")
        self.mates.decline(self.bob, self.ann)
        self.mates.cancel(self.ann, self.bob)
        # Ann took her request back, so Bob adding her must not skip her consent.
        self.assertEqual(self.mates.request(self.bob, "ann")["relation"],
                         "requested")
        self.assertEqual(self.rel(self.ann, "bob"), "incoming")

    def test_refusals(self):
        with self.assertRaises(LookupError):
            self.mates.request(self.ann, "nobody")
        with self.assertRaises(ValueError) as cm:
            self.mates.request(self.ann, "@Ann")
        self.assertIn("own", str(cm.exception))
        self.befriend(self.ann, "ann", self.bob, "bob")
        with self.assertRaises(ValueError) as cm:
            self.mates.request(self.ann, "bob")
        self.assertIn("already", str(cm.exception))

    def test_requests_are_capped(self):
        for i in range(MAX_REQUESTS):
            self.users.create(f"U{i}", f"user_{i}")
            self.mates.request(self.ann, f"user_{i}")
        with self.assertRaises(ValueError) as cm:
            self.mates.request(self.ann, "bob")
        self.assertIn(str(MAX_REQUESTS), str(cm.exception))
        # A declined request still counts, so the cap cannot be used to learn
        # which requests were declined.
        self.mates.decline(self.users.by_username("user_0")["id"], self.ann)
        with self.assertRaises(ValueError):
            self.mates.request(self.ann, "bob")
        # Answering someone's request to you is not a new request.
        self.mates.request(self.bob, "ann")
        self.assertEqual(self.mates.request(self.ann, "bob")["relation"], "mate")


class TestMates(MatesCase):

    def test_either_side_can_remove_and_a_new_request_is_then_allowed(self):
        self.befriend(self.ann, "ann", self.bob, "bob")
        self.assertTrue(self.mates.remove(self.bob, self.ann))
        self.assertFalse(self.mates.remove(self.ann, self.bob))
        self.assertEqual(self.mates.social(self.ann)["mates"], [])
        self.assertEqual(self.mates.request(self.ann, "bob")["relation"],
                         "requested")

    def test_deleting_a_user_clears_their_requests_and_pairs(self):
        cy = self.users.create("Cy", "cy_")["id"]
        self.befriend(self.ann, "ann", self.bob, "bob")
        self.mates.request(cy, "ann")
        self.users.delete(self.bob)
        self.users.delete(cy)
        s = self.mates.social(self.ann)
        self.assertEqual((s["mates"], s["incoming"], s["outgoing"]), ([], [], []))

    def test_mates_are_ranked_by_wingspan(self):
        cy = self.users.create("Cy", "cy_")["id"]
        self.befriend(self.ann, "ann", self.bob, "bob")
        self.befriend(self.ann, "ann", cy, "cy_")
        self.history.for_user(self.bob).add("2024-01-01", "ATL", "JFK")
        self.history.for_user(cy).add("2024-01-01", "ATL", "NRT")
        s = self.mates.social(self.ann)
        self.assertEqual([m["username"] for m in s["mates"]], ["cy_", "bob"])
        self.assertEqual(s["me"]["stats"]["distance_mi"], 0)


class TestPrivacy(MatesCase):

    def setUp(self):
        super().setUp()
        h = self.history.for_user(self.bob)
        for day in ("2024-03-09", "2024-04-09", "2024-05-09"):
            h.add(day, "LHR", "ATL", airline="Delta", flight_number="DL31",
                  aircraft="A333", seat="34A", notes="secret")
        h.add("2024-03-16", "ATL", "LHR")
        h.add("2024-06-01", "ATL", "JFK")

    def test_social_payload_has_exactly_the_allowed_fields(self):
        self.befriend(self.ann, "ann", self.bob, "bob")
        s = self.mates.social(self.ann)
        mate = s["mates"][0]
        self.assertEqual(set(mate), PERSON | {"stats"})
        self.assertEqual(set(mate["stats"]), {"flights", "distance_mi",
                                              "distance_km", "airports",
                                              "countries"})
        self.assertEqual(mate["stats"]["flights"], 5)
        self.assertEqual(keys(s) & PRIVATE, set())

    def test_routes_are_distinct_undirected_and_bare(self):
        self.befriend(self.ann, "ann", self.bob, "bob")
        routes = self.mates.routes(self.ann, self.bob)
        # Four ATL-LHR flights in both directions collapse to one route, always
        # listed alphabetically so the direction flown is not revealed.
        self.assertEqual([(r["from"]["iata"], r["to"]["iata"]) for r in routes],
                         [("ATL", "JFK"), ("ATL", "LHR")])
        self.assertEqual(set(routes[0]), {"from", "to"})
        self.assertEqual(set(routes[0]["from"]),
                         {"iata", "name", "city", "country", "lat", "lon"})
        self.assertEqual(keys(routes) & PRIVATE, set())

    def test_routes_are_refused_unless_mates(self):
        self.assertIsNone(self.mates.routes(self.ann, self.bob))
        self.mates.request(self.ann, "bob")
        self.assertIsNone(self.mates.routes(self.ann, self.bob))
        self.assertIsNone(self.mates.routes(self.bob, self.ann))
        self.assertIsNone(self.mates.routes(self.ann, 999))
        self.assertIsNone(self.mates.routes(self.ann, self.ann))

    def test_a_flight_with_an_unknown_airport_is_skipped_not_fatal(self):
        with closing(connect(self.history.path)) as db, db:
            db.execute("INSERT INTO flights (user_id, date, origin, dest,"
                       " distance_km, created_at) VALUES (?,?,?,?,?,?)",
                       (self.bob, "2025-01-01", "ZZZ", "ATL", 500.0, "t"))
        self.befriend(self.ann, "ann", self.bob, "bob")
        self.assertEqual(self.mates.social(self.ann)["mates"][0]["stats"]["flights"], 6)
        self.assertEqual(len(self.mates.routes(self.ann, self.bob)), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_mates -v`
Expected: `ModuleNotFoundError: No module named 'fc.mates'`

- [ ] **Step 4: Implement**

Create `fc/mates.py`:

```python
"""Mate requests and pairs, and the only code that describes one user to
another. Everything returned about someone else is built from the explicit
field lists below, so private flight details cannot leak by accident.

A request row has one of three states:
  pending    waiting for the recipient
  declined   refused; the sender still sees "Requested" and is not told
  withdrawn  declined, then cancelled by the sender; hidden from both, but a
             new request from the same sender still does not reach them
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime

from .db import connect
from .history import History
from .users import Users

MAX_REQUESTS = 20

PERSON_FIELDS = ("id", "username", "name", "picture_url")
STAT_FIELDS = ("flights", "distance_mi", "distance_km", "airports", "countries")
AIRPORT_FIELDS = ("iata", "name", "city", "country", "lat", "lon")

# States in which the sender sees "Requested".
_SHOWN = ("pending", "declined")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _status(db: sqlite3.Connection, from_id: int, to_id: int) -> str | None:
    row = db.execute(
        "SELECT status FROM mate_requests WHERE from_id = ? AND to_id = ?",
        (from_id, to_id)).fetchone()
    return row["status"] if row else None


def _are_mates(db: sqlite3.Connection, a: int, b: int) -> bool:
    lo, hi = sorted((a, b))
    return db.execute("SELECT 1 FROM mates WHERE user_lo = ? AND user_hi = ?",
                      (lo, hi)).fetchone() is not None


def _relation(db: sqlite3.Connection, viewer: int, other: int) -> str:
    if viewer == other:
        return "self"
    if _are_mates(db, viewer, other):
        return "mate"
    if _status(db, viewer, other) in _SHOWN:
        return "requested"
    if _status(db, other, viewer) == "pending":
        return "incoming"
    return "none"


def _join(db: sqlite3.Connection, a: int, b: int) -> None:
    db.execute(
        "DELETE FROM mate_requests WHERE (from_id = ? AND to_id = ?)"
        " OR (from_id = ? AND to_id = ?)", (a, b, b, a))
    lo, hi = sorted((a, b))
    db.execute("INSERT OR IGNORE INTO mates (user_lo, user_hi, created_at)"
               " VALUES (?,?,?)", (lo, hi, _now()))


class Mates:
    def __init__(self, users: Users, history: History):
        self.users = users
        self.history = history
        self.path = history.path

    # ----------------------------------------------------------------- lookup
    def card(self, viewer_id: int, username: str) -> dict | None:
        """What anyone may see of the person with exactly this username."""
        person = self.users.by_username(username)
        if person is None:
            return None
        with closing(connect(self.path)) as db:
            relation = _relation(db, viewer_id, person["id"])
        return {**{k: person[k] for k in PERSON_FIELDS}, "relation": relation}

    # --------------------------------------------------------------- requests
    def request(self, from_id: int, username: str) -> dict:
        target = self.users.by_username(username)
        if target is None:
            raise LookupError("no one has that username")
        to_id = target["id"]
        if to_id == from_id:
            raise ValueError("that is your own username")
        with closing(connect(self.path)) as db, db:
            if _are_mates(db, from_id, to_id):
                raise ValueError("you are already mates")
            mine, theirs = _status(db, from_id, to_id), _status(db, to_id, from_id)
            if theirs in _SHOWN:
                # They asked first (even if it was declined): adding them back
                # is the answer to their request.
                _join(db, from_id, to_id)
            elif mine in _SHOWN:
                pass
            elif mine == "withdrawn":
                db.execute(
                    "UPDATE mate_requests SET status = 'declined'"
                    " WHERE from_id = ? AND to_id = ?", (from_id, to_id))
            else:
                waiting = db.execute(
                    "SELECT COUNT(*) FROM mate_requests WHERE from_id = ?"
                    " AND status IN ('pending', 'declined')",
                    (from_id,)).fetchone()[0]
                if waiting >= MAX_REQUESTS:
                    raise ValueError(
                        f"you have {MAX_REQUESTS} requests waiting; "
                        "cancel one before sending another")
                # A request of theirs that they withdrew no longer counts.
                db.execute(
                    "DELETE FROM mate_requests WHERE from_id = ? AND to_id = ?",
                    (to_id, from_id))
                db.execute(
                    "INSERT INTO mate_requests (from_id, to_id, status,"
                    " created_at) VALUES (?, ?, 'pending', ?)",
                    (from_id, to_id, _now()))
            relation = _relation(db, from_id, to_id)
        return {**{k: target[k] for k in PERSON_FIELDS}, "relation": relation}

    def accept(self, user_id: int, other_id: int) -> bool:
        with closing(connect(self.path)) as db, db:
            if _status(db, other_id, user_id) != "pending":
                return False
            _join(db, user_id, other_id)
            return True

    def decline(self, user_id: int, other_id: int) -> bool:
        with closing(connect(self.path)) as db, db:
            return db.execute(
                "UPDATE mate_requests SET status = 'declined'"
                " WHERE from_id = ? AND to_id = ? AND status = 'pending'",
                (other_id, user_id)).rowcount > 0

    def cancel(self, user_id: int, other_id: int) -> bool:
        with closing(connect(self.path)) as db, db:
            status = _status(db, user_id, other_id)
            if status == "pending":
                db.execute(
                    "DELETE FROM mate_requests WHERE from_id = ? AND to_id = ?",
                    (user_id, other_id))
            elif status == "declined":
                db.execute(
                    "UPDATE mate_requests SET status = 'withdrawn'"
                    " WHERE from_id = ? AND to_id = ?", (user_id, other_id))
            else:
                return False
            return True

    def remove(self, user_id: int, other_id: int) -> bool:
        lo, hi = sorted((user_id, other_id))
        with closing(connect(self.path)) as db, db:
            return db.execute(
                "DELETE FROM mates WHERE user_lo = ? AND user_hi = ?",
                (lo, hi)).rowcount > 0

    # ------------------------------------------------------------------ views
    def _person(self, user_id: int, with_stats: bool = False) -> dict:
        user = self.users.get(user_id)
        out = {k: user[k] for k in PERSON_FIELDS}
        if with_stats:
            stats = self.history.for_user(user_id).stats()
            out["stats"] = {k: stats[k] for k in STAT_FIELDS}
        return out

    def social(self, user_id: int) -> dict:
        with closing(connect(self.path)) as db:
            mate_ids = [r[0] for r in db.execute(
                "SELECT user_hi FROM mates WHERE user_lo = ?"
                " UNION SELECT user_lo FROM mates WHERE user_hi = ?",
                (user_id, user_id))]
            incoming = [r[0] for r in db.execute(
                "SELECT from_id FROM mate_requests WHERE to_id = ?"
                " AND status = 'pending' ORDER BY created_at DESC", (user_id,))]
            outgoing = [r[0] for r in db.execute(
                "SELECT to_id FROM mate_requests WHERE from_id = ?"
                " AND status IN ('pending', 'declined')"
                " ORDER BY created_at DESC", (user_id,))]
        mates = sorted((self._person(i, with_stats=True) for i in mate_ids),
                       key=lambda m: (-m["stats"]["distance_mi"], m["username"]))
        return {"me": self._person(user_id, with_stats=True),
                "mates": mates,
                "incoming": [self._person(i) for i in incoming],
                "outgoing": [self._person(i) for i in outgoing]}

    def routes(self, viewer_id: int, mate_id: int) -> list[dict] | None:
        """A mate's distinct routes, or None if the two are not mates. Each
        airport pair appears once, alphabetically, so neither the direction
        nor the number of times it was flown is revealed."""
        with closing(connect(self.path)) as db:
            if not _are_mates(db, viewer_id, mate_id):
                return None
        pairs: dict[tuple[str, str], dict] = {}
        for f in self.history.for_user(mate_id).list():
            ends = sorted((f["from"], f["to"]), key=lambda a: a["iata"])
            if any(a.get("lat") is None for a in ends):
                continue          # airport no longer in the table
            key = (ends[0]["iata"], ends[1]["iata"])
            pairs[key] = {"from": {k: ends[0][k] for k in AIRPORT_FIELDS},
                          "to": {k: ends[1][k] for k in AIRPORT_FIELDS}}
        return [pairs[k] for k in sorted(pairs)]
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_mates -v`
Expected: 21 tests, `OK`.

- [ ] **Step 6: Commit**

```bash
git add fc/mates.py tests/helpers.py tests/test_mates.py
git commit -m "Add mate requests, pairs and the mate-visible view

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Flask app — current user, guard, history and live routes

**Files:**
- Create: `fc/webapp.py`, `tests/test_webapp.py`
- Delete: `fc/server.py`
- Modify: `run.py`, `.claude/launch.json`

**Interfaces:**
- Consumes: `Config`; `History.for_user`; `Users.get`, `.by_username`, `.create`, `.ensure_local`; `validate_username`, `normalize_username`; `Mates` (constructed here, routes added in Task 7); `Tracker` methods `snapshot()`, `track(cs)`, `untrack(key)`, `poll_once()`, `nearby(lat, lon, dist)`, `where_is_aircraft(reg)`.
- Produces: `fc.webapp.create_app(config: Config, tracker=None, airports: Airports | None = None) -> Flask`. Live routes exist only when `tracker` is not `None`. Routes in this task:

```
GET  /                         index.html
GET  /static/<path>            files from web/
GET  /api/me                   {id, username, name, picture_url, auth, live, dev_users}
GET  /api/history              POST /api/history
POST /api/history/update       POST /api/history/delete     POST /api/history/import
GET  /api/history/export.csv   GET  /api/history/template.csv
GET  /api/airports?q=
POST /dev/login {username}     only when config.dev_users
GET  /api/state   POST /api/track   POST /api/untrack   POST /api/poll
GET  /api/nearby  GET  /api/aircraft                       only when tracker
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_webapp.py`:

```python
"""Web layer tests, through Flask's test client. Offline."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.config import Config
from fc.webapp import create_app
from tests.helpers import stores

ORIGIN = {"Origin": "http://localhost"}


class FakeTracker:
    def snapshot(self):
        return {"flights": [], "alerts": [], "log": [], "status": {"tracked": 0}}


class WebCase(unittest.TestCase):
    dev_users = True
    tracker = None

    def setUp(self):
        self.dir, self.airports, self.history, self.users = stores(self)
        self.app = create_app(
            Config(data_dir=self.dir, dev_users=self.dev_users, live=False),
            tracker=self.tracker, airports=self.airports)
        self.client = self.app.test_client()

    def post(self, path, body=None, client=None, **kw):
        return (client or self.client).post(path, json=body or {},
                                            headers=ORIGIN, **kw)

    def login(self, username):
        client = self.app.test_client()
        self.assertEqual(self.post("/dev/login", {"username": username},
                                   client).status_code, 200)
        return client


class TestMe(WebCase):

    def test_requests_act_as_the_local_user(self):
        me = self.client.get("/api/me").get_json()
        self.assertEqual((me["username"], me["name"]), ("you", "You"))
        self.assertEqual((me["auth"], me["live"], me["dev_users"]),
                         ("local", False, True))
        self.assertNotIn("email", me)

    def test_dev_login_switches_user_and_back(self):
        ann = self.login("Ann")
        self.assertEqual(ann.get("/api/me").get_json()["username"], "ann")
        self.assertEqual(self.client.get("/api/me").get_json()["username"], "you")
        self.post("/dev/login", {"username": "you"}, ann)
        self.assertEqual(ann.get("/api/me").get_json()["username"], "you")

    def test_dev_login_refuses_a_bad_username(self):
        r = self.post("/dev/login", {"username": "no"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("3 to 20", r.get_json()["error"])

    def test_a_session_for_a_deleted_user_falls_back_to_the_local_user(self):
        ann = self.login("ann")
        self.users.delete(self.users.by_username("ann")["id"])
        r = ann.get("/api/me")
        self.assertEqual((r.status_code, r.get_json()["username"]), (200, "you"))


class TestGuard(WebCase):

    def test_a_post_without_a_matching_origin_is_refused(self):
        body = {"date": "2024-03-09", "from": "ATL", "to": "LHR"}
        for headers in ({}, {"Origin": "http://evil.example"},
                        {"Origin": "http://localhost:9999"}):
            r = self.client.post("/api/history", json=body, headers=headers)
            self.assertEqual(r.status_code, 403, headers)
        self.assertEqual(self.client.get("/api/history").get_json()["flights"], [])

    def test_a_post_that_is_not_json_is_refused(self):
        r = self.client.post("/api/history", data="date=2024-03-09",
                             headers=ORIGIN)
        self.assertEqual(r.status_code, 403)

    def test_a_body_that_is_not_a_json_object_is_a_400(self):
        for raw in ("[1, 2]", "{broken", '"text"'):
            r = self.client.post("/api/history", data=raw, headers=ORIGIN,
                                 content_type="application/json")
            self.assertEqual(r.status_code, 400, raw)
            self.assertIn("error", r.get_json())

    def test_unknown_api_paths_answer_in_json(self):
        r = self.client.get("/api/nope")
        self.assertEqual((r.status_code, r.get_json()), (404, {"error": "not found"}))


class TestHistoryRoutes(WebCase):

    def add(self, client=None, **over):
        body = {"date": "2024-03-09", "from": "ATL", "to": "LHR", **over}
        return self.post("/api/history", body, client)

    def test_add_list_update_delete(self):
        f = self.add(airline="Delta").get_json()
        self.assertEqual((f["from"]["iata"], f["airline"]), ("ATL", "Delta"))
        snap = self.client.get("/api/history").get_json()
        self.assertEqual(snap["stats"]["flights"], 1)
        g = self.post("/api/history/update",
                      {"id": f["id"], "date": "2024-03-10", "from": "ATL",
                       "to": "JFK"}).get_json()
        self.assertEqual((g["to"]["iata"], g["airline"]), ("JFK", ""))
        self.assertEqual(self.post("/api/history/delete",
                                   {"id": f["id"]}).get_json(), {"removed": True})

    def test_bad_input_is_a_400_with_the_reason(self):
        r = self.add(to="ZZZ")
        self.assertEqual(r.status_code, 400)
        self.assertIn("ZZZ", r.get_json()["error"])
        self.assertEqual(self.post("/api/history/update", {}).status_code, 400)
        self.assertEqual(self.post("/api/history/delete", {}).status_code, 400)
        self.assertEqual(self.post("/api/history/import", {}).status_code, 400)

    def test_users_cannot_touch_each_others_flights(self):
        ann, bob = self.login("ann"), self.login("bob")
        f = self.add(ann).get_json()
        self.assertEqual(bob.get("/api/history").get_json()["flights"], [])
        r = self.post("/api/history/update",
                      {"id": f["id"], "date": "2024-03-10", "from": "ATL",
                       "to": "JFK"}, bob)
        missing = self.post("/api/history/update",
                            {"id": 999, "date": "2024-03-10", "from": "ATL",
                             "to": "JFK"}, bob)
        self.assertEqual((r.status_code, r.get_json()),
                         (missing.status_code, missing.get_json()))
        self.assertEqual(self.post("/api/history/delete", {"id": f["id"]},
                                   bob).get_json(), {"removed": False})
        self.assertEqual(len(ann.get("/api/history").get_json()["flights"]), 1)

    def test_export_downloads_csv_that_imports_back(self):
        self.add(flight_number="DL30")
        r = self.client.get("/api/history/export.csv")
        self.assertTrue(r.headers["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment", r.headers["Content-Disposition"])
        bob = self.login("bob")
        self.assertEqual(self.post("/api/history/import",
                                   {"csv": r.get_data(as_text=True)},
                                   bob).get_json()["added"], 1)

    def test_template_and_airport_search(self):
        self.assertTrue(self.client.get("/api/history/template.csv")
                        .get_data(as_text=True).startswith("date,from,to"))
        found = self.client.get("/api/airports?q=lond").get_json()["airports"]
        self.assertEqual([a["iata"] for a in found], ["LHR"])


class TestModes(WebCase):
    dev_users = False

    def test_dev_login_does_not_exist_unless_enabled(self):
        self.assertEqual(self.post("/dev/login", {"username": "ann"}).status_code,
                         404)

    def test_live_routes_do_not_exist_without_a_tracker(self):
        self.assertEqual(self.client.get("/api/state").status_code, 404)
        self.assertEqual(self.post("/api/poll").status_code, 404)


class TestLive(WebCase):
    tracker = FakeTracker()

    def test_live_routes_exist_with_a_tracker(self):
        self.assertTrue(self.client.get("/api/me").get_json()["live"])
        self.assertEqual(self.client.get("/api/state").get_json()["status"],
                         {"tracked": 0})


class TestPages(WebCase):

    def test_index_and_static_files_are_served(self):
        self.assertIn(b"Wingmates", self.client.get("/").data)
        self.assertEqual(self.client.get("/static/style.css").status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_webapp -v`
Expected: `ModuleNotFoundError: No module named 'fc.webapp'`

- [ ] **Step 3: Implement the app**

Create `fc/webapp.py`:

```python
"""The Flask app: every HTTP route. The only module that knows about requests.

There is no real sign-in yet. Every request acts as the local user, unless
dev users are enabled and the session names another one.
"""
from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import urlsplit

from flask import (Flask, Response, g, jsonify, request, send_from_directory,
                   session)
from werkzeug.exceptions import HTTPException

from .adsb import FeedError
from .airports import Airports
from .config import Config
from .history import OPTIONAL, History, template_csv
from .mates import Mates
from .users import Users, normalize_username, validate_username

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def create_app(config: Config, tracker=None,
               airports: Airports | None = None) -> Flask:
    app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="/static")
    app.secret_key = config.secret_key or secrets.token_hex(32)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.base_url.startswith("https://"),
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )

    history = History(airports, config.db_path)
    users = Users(config.db_path)
    mates = Mates(users, history)

    # ------------------------------------------------------------- helpers
    def current_user() -> dict:
        if config.dev_users:
            uid = session.get("uid")
            user = users.get(uid) if uid else None
            if user:
                return user
        return users.ensure_local()

    def body() -> dict:
        data = request.get_json(silent=True)
        if data is None and not request.get_data():
            return {}
        if not isinstance(data, dict):
            raise ApiError("the request body must be a JSON object")
        return data

    def flights():
        return history.for_user(g.user["id"])

    def flight_fields(data: dict) -> dict:
        return {k: str(data.get(k) or "") for k in OPTIONAL}

    @app.errorhandler(ApiError)
    def api_error(e: ApiError):
        return jsonify(error=e.message), e.status

    @app.errorhandler(HTTPException)
    def http_error(e: HTTPException):
        if request.path.startswith(("/api/", "/dev/")):
            return jsonify(error=e.name.lower()), e.code
        return e

    @app.before_request
    def guard():
        if request.method == "POST":
            origin = urlsplit(request.headers.get("Origin", "")).netloc
            if not origin or origin != request.host:
                raise ApiError("cross-site request refused", 403)
            if not request.is_json:
                raise ApiError("requests must be JSON", 403)
        if request.path.startswith(("/api/", "/dev/")):
            g.user = current_user()

    @app.after_request
    def caching(resp: Response) -> Response:
        resp.headers["Cache-Control"] = (
            "no-store" if request.path.startswith("/api/") else "no-cache")
        return resp

    # --------------------------------------------------------------- pages
    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/api/me")
    def me():
        return jsonify({**g.user, "auth": config.auth,
                        "live": tracker is not None,
                        "dev_users": config.dev_users})

    # ------------------------------------------------------------- history
    @app.get("/api/history")
    def history_list():
        return jsonify(flights().snapshot())

    @app.post("/api/history")
    def history_add():
        data = body()
        try:
            return jsonify(flights().add(data.get("date"), data.get("from"),
                                         data.get("to"), **flight_fields(data)))
        except ValueError as e:
            raise ApiError(str(e)) from None

    @app.post("/api/history/update")
    def history_update():
        data = body()
        try:
            fid = int(data.get("id"))
        except (TypeError, ValueError):
            raise ApiError("id is required") from None
        try:
            found = flights().update(fid, data.get("date"), data.get("from"),
                                     data.get("to"), **flight_fields(data))
        except ValueError as e:
            raise ApiError(str(e)) from None
        if found is None:
            raise ApiError("no such flight", 404)
        return jsonify(found)

    @app.post("/api/history/delete")
    def history_delete():
        try:
            fid = int(body().get("id"))
        except (TypeError, ValueError):
            raise ApiError("id is required") from None
        return jsonify(removed=flights().delete(fid))

    @app.post("/api/history/import")
    def history_import():
        text = body().get("csv")
        if not isinstance(text, str) or not text.strip():
            raise ApiError("csv is required")
        try:
            return jsonify(flights().import_csv(text))
        except ValueError as e:
            raise ApiError(str(e)) from None

    def _csv(text: str, filename: str) -> Response:
        return Response(text, mimetype="text/csv", headers={
            "Content-Disposition": f'attachment; filename="{filename}"'})

    @app.get("/api/history/export.csv")
    def history_export():
        return _csv(flights().export_csv(), "wingmates-flights.csv")

    @app.get("/api/history/template.csv")
    def history_template():
        return _csv(template_csv(), "flights-template.csv")

    @app.get("/api/airports")
    def airport_search():
        found = history.airports.search(request.args.get("q", ""))
        return jsonify(airports=[a.to_json() for a in found])

    # ----------------------------------------------------------- dev users
    if config.dev_users:
        @app.post("/dev/login")
        def dev_login():
            raw = body().get("username")
            if normalize_username(raw) == "you":
                session.pop("uid", None)
                return jsonify(users.ensure_local())
            try:
                name = validate_username(raw)
            except ValueError as e:
                raise ApiError(str(e)) from None
            user = users.by_username(name) or users.create(name, name)
            session["uid"] = user["id"]
            return jsonify(user)

    # ---------------------------------------------------------------- live
    if tracker is not None:
        @app.get("/api/state")
        def live_state():
            return jsonify(tracker.snapshot())

        @app.post("/api/track")
        def live_track():
            cs = str(body().get("callsign") or "").strip()
            if not cs:
                raise ApiError("callsign is required")
            try:
                return jsonify(tracker.track(cs))
            except LookupError as e:
                raise ApiError(str(e), 404) from None
            except ValueError as e:
                raise ApiError(str(e)) from None

        @app.post("/api/untrack")
        def live_untrack():
            key = str(body().get("key") or "").strip()
            if not key:
                raise ApiError("key is required")
            return jsonify(removed=tracker.untrack(key))

        @app.post("/api/poll")
        def live_poll():
            return jsonify(updated=tracker.poll_once())

        @app.get("/api/nearby")
        def live_nearby():
            try:
                lat = float(request.args.get("lat", "33.64"))
                lon = float(request.args.get("lon", "-84.43"))
                dist = int(float(request.args.get("dist", "60")))
            except ValueError:
                raise ApiError("lat, lon and dist must be numbers") from None
            try:
                return jsonify(aircraft=tracker.nearby(lat, lon, dist))
            except FeedError as e:
                raise ApiError(f"feed unavailable: {e}", 503) from None

        @app.get("/api/aircraft")
        def live_aircraft():
            reg = request.args.get("reg", "").strip()
            if not reg:
                raise ApiError("reg is required")
            try:
                found = tracker.where_is_aircraft(reg)
            except FeedError as e:
                raise ApiError(f"feed unavailable: {e}", 503) from None
            if found is None:
                raise ApiError(f"{reg.upper()} is not transmitting right now", 404)
            return jsonify(found)

    return app
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_webapp -v`
Expected: 17 tests, `OK`.

- [ ] **Step 5: Replace the old server in `run.py`**

Delete the old server: `git rm fc/server.py`

In `run.py`, keep the module docstring and the `BANNER` constant exactly as they are. Replace the import block and `main()` with:

```python
from __future__ import annotations

import argparse
import logging
import sys
import threading
import webbrowser

from fc import tracker as tracker_mod
from fc.config import Config
from fc.tracker import POLL_INTERVAL_S, Tracker
from fc.webapp import create_app
```

```python
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8817)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    try:
        cfg = Config.from_env()
    except ValueError as e:
        print(f"  configuration error: {e}")
        return 1

    print(BANNER)
    tracker = None
    if cfg.live:
        # The tracker reads these module globals when it loads and saves.
        tracker_mod.STATE_DIR = cfg.data_dir
        tracker_mod.STATE_FILE = cfg.data_dir / "state.json"
        tracker = Tracker()
        if tracker.flights:
            print(f"  resumed {len(tracker.flights)} tracked flight(s)")

    app = create_app(cfg, tracker)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    url = f"http://{args.host}:{args.port}"
    print(f"  open   {url}")
    print(f"  data   {cfg.data_dir}")
    if tracker:
        print(f"  live   adsb.lol (primary) · opensky (fallback),"
              f" every {POLL_INTERVAL_S}s")
    else:
        print("  live   off")
    if cfg.dev_users:
        print("  dev    user switching is ON; do not expose this server")
    print("\n  ctrl-c to stop.\n")

    if tracker:
        tracker.start()
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)
    finally:
        if tracker:
            tracker.stop()
    return 0
```

- [ ] **Step 6: Point the launch config at the virtualenv**

Replace `.claude/launch.json` with:

```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "wingmates",
      "runtimeExecutable": ".venv/bin/python",
      "runtimeArgs": ["run.py", "--no-browser"],
      "port": 8817
    },
    {
      "name": "wingmates-dev",
      "runtimeExecutable": "env",
      "runtimeArgs": ["WINGMATES_DEV_USERS=1", "WINGMATES_DATA_DIR=.devdata",
                      ".venv/bin/python", "run.py", "--no-browser"],
      "port": 8817
    }
  ]
}
```

`wingmates-dev` keeps its made-up users in `.devdata/`, so they never enter the real `~/.wingmates`.

- [ ] **Step 7: Run everything and smoke-test the server**

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: `OK`.

Run:

```bash
WINGMATES_DATA_DIR=.devdata WINGMATES_LIVE=0 .venv/bin/python run.py --no-browser --port 8899 &
sleep 2
curl -s http://127.0.0.1:8899/api/me
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8899/api/state
kill %1
```

Expected: a JSON object with `"username": "you"` and `"live": false`, then `404`.

- [ ] **Step 8: Commit**

```bash
git add fc/webapp.py run.py tests/test_webapp.py .claude/launch.json   # the fc/server.py removal is already staged by git rm
git commit -m "Replace the stdlib server with a Flask app scoped to the current user

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Social routes

**Files:**
- Modify: `fc/webapp.py` (add routes before the `# ----- dev users` section)
- Modify: `tests/test_webapp.py`

**Interfaces:**
- Consumes: `Mates.card`, `.request`, `.accept`, `.decline`, `.cancel`, `.remove`, `.social`, `.routes`.
- Produces:

```
GET  /api/social                     Mates.social(me)
GET  /api/users/lookup?username=     Mates.card(me, username), or 404
POST /api/mates/request {username}   the card after the request
POST /api/mates/<id>/accept          {"ok": true}, or 404
POST /api/mates/<id>/decline         {"ok": true}, or 404
POST /api/mates/<id>/cancel          {"ok": true}, or 404
POST /api/mates/<id>/remove          {"ok": true}, or 404
GET  /api/mates/<id>/routes          {"routes": [...]}, or 404
```

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_webapp.py`, above the `if __name__` line:

```python
PRIVATE = {"email", "date", "airline", "flight_number", "aircraft", "seat",
           "notes", "google_sub"}


def keys(obj):
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in keys(v)}
    return set()


class TestSocialRoutes(WebCase):

    def setUp(self):
        super().setUp()
        self.ann, self.bob = self.login("ann"), self.login("bob")
        self.bob_id = self.users.by_username("bob")["id"]
        self.ann_id = self.users.by_username("ann")["id"]
        self.post("/api/history", {"date": "2024-03-09", "from": "ATL",
                                   "to": "LHR", "airline": "Delta",
                                   "seat": "34A", "notes": "secret"}, self.bob)

    def test_lookup_takes_usernames_the_way_people_type_them(self):
        r = self.ann.get("/api/users/lookup?username=%40Bob%20")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {
            "id": self.bob_id, "username": "bob", "name": "bob",
            "picture_url": None, "relation": "none"})
        for q in ("bo", "nobody", ""):
            r = self.ann.get(f"/api/users/lookup?username={q}")
            self.assertEqual((r.status_code, r.get_json()),
                             (404, {"error": "no one has that username"}))

    def test_request_accept_compare_and_remove(self):
        r = self.post("/api/mates/request", {"username": "bob"}, self.ann)
        self.assertEqual(r.get_json()["relation"], "requested")
        s = self.bob.get("/api/social").get_json()
        self.assertEqual([p["username"] for p in s["incoming"]], ["ann"])

        self.assertEqual(self.post(f"/api/mates/{self.ann_id}/accept",
                                   client=self.bob).get_json(), {"ok": True})
        s = self.ann.get("/api/social").get_json()
        self.assertEqual(s["mates"][0]["username"], "bob")
        self.assertGreater(s["mates"][0]["stats"]["distance_mi"], 4000)
        self.assertEqual(keys(s) & PRIVATE, set())

        routes = self.ann.get(f"/api/mates/{self.bob_id}/routes").get_json()
        self.assertEqual([(r["from"]["iata"], r["to"]["iata"])
                          for r in routes["routes"]], [("ATL", "LHR")])
        self.assertEqual(keys(routes) & PRIVATE, set())

        self.assertEqual(self.post(f"/api/mates/{self.bob_id}/remove",
                                   client=self.ann).status_code, 200)
        self.assertEqual(self.bob.get("/api/social").get_json()["mates"], [])

    def test_decline_and_cancel(self):
        self.post("/api/mates/request", {"username": "bob"}, self.ann)
        self.assertEqual(self.post(f"/api/mates/{self.ann_id}/decline",
                                   client=self.bob).status_code, 200)
        self.assertEqual(self.post(f"/api/mates/{self.ann_id}/decline",
                                   client=self.bob).status_code, 404)
        self.assertEqual(self.post(f"/api/mates/{self.bob_id}/cancel",
                                   client=self.ann).status_code, 200)
        self.assertEqual(self.ann.get("/api/social").get_json()["outgoing"], [])

    def test_request_errors(self):
        r = self.post("/api/mates/request", {"username": "nobody"}, self.ann)
        self.assertEqual(r.status_code, 404)
        r = self.post("/api/mates/request", {"username": "ann"}, self.ann)
        self.assertEqual(r.status_code, 400)
        self.assertIn("own", r.get_json()["error"])

    def test_routes_of_a_stranger_look_like_a_missing_user(self):
        stranger = self.ann.get(f"/api/mates/{self.bob_id}/routes")
        missing = self.ann.get("/api/mates/999/routes")
        self.assertEqual(stranger.status_code, 404)
        self.assertEqual(stranger.get_json(), missing.get_json())
        self.post("/api/mates/request", {"username": "bob"}, self.ann)
        self.assertEqual(
            self.ann.get(f"/api/mates/{self.bob_id}/routes").status_code, 404)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_webapp.TestSocialRoutes -v`
Expected: failures with status `404` where `200` was expected.

- [ ] **Step 3: Implement**

In `fc/webapp.py`, insert immediately before the line `    # ----------------------------------------------------------- dev users`:

```python
    # -------------------------------------------------------------- social
    @app.get("/api/social")
    def social():
        return jsonify(mates.social(g.user["id"]))

    @app.get("/api/users/lookup")
    def lookup():
        card = mates.card(g.user["id"], request.args.get("username", ""))
        if card is None:
            raise ApiError("no one has that username", 404)
        return jsonify(card)

    @app.post("/api/mates/request")
    def mate_request():
        try:
            return jsonify(mates.request(g.user["id"],
                                         str(body().get("username") or "")))
        except LookupError as e:
            raise ApiError(str(e), 404) from None
        except ValueError as e:
            raise ApiError(str(e)) from None

    def _mate_action(action, other_id: int, missing: str):
        if not action(g.user["id"], other_id):
            raise ApiError(missing, 404)
        return jsonify(ok=True)

    @app.post("/api/mates/<int:other_id>/accept")
    def mate_accept(other_id: int):
        return _mate_action(mates.accept, other_id, "no such request")

    @app.post("/api/mates/<int:other_id>/decline")
    def mate_decline(other_id: int):
        return _mate_action(mates.decline, other_id, "no such request")

    @app.post("/api/mates/<int:other_id>/cancel")
    def mate_cancel(other_id: int):
        return _mate_action(mates.cancel, other_id, "no such request")

    @app.post("/api/mates/<int:other_id>/remove")
    def mate_remove(other_id: int):
        return _mate_action(mates.remove, other_id, "not found")

    @app.get("/api/mates/<int:other_id>/routes")
    def mate_routes(other_id: int):
        routes = mates.routes(g.user["id"], other_id)
        if routes is None:
            raise ApiError("not found", 404)
        return jsonify(routes=routes)

```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add fc/webapp.py tests/test_webapp.py
git commit -m "Add social routes: lookup, requests, mates and routes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Front-end foundation — escaping, JSON posts, boot from /api/me

**Files:**
- Modify: `web/app.js`, `web/history.js`, `web/index.html`, `web/style.css`

There is no JavaScript test runner in this project. Each step is checked with `node --check`, and the task ends with a browser check.

**Interfaces:**
- Consumes: `GET /api/me`, `POST /dev/login`, `GET /api/history/export.csv`.
- Produces, as globals in `web/app.js` for the other scripts:
  - `esc(value) -> string` — HTML-escapes.
  - `post(path, body) -> Promise<object>` — JSON `POST`; every write must use it.
  - `meReady` — a Promise resolving to the `/api/me` object.
  - A `tab` event on `document` with `detail` = the tab name, fired by `showTab` in `web/history.js`.
  - `mapRoutes(key, routes, airports, colour)` in `web/history.js` — draws or clears one named route layer on the flat map.

- [ ] **Step 1: Add the shared helpers to `web/app.js`**

Replace the `api` function with:

```js
async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ error: 'bad response' }));
  if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
  return data;
}

// Every write goes through here: the server refuses a POST that is not JSON.
const post = (path, body) => api(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
});

// Values from the feed and from other people are never trusted as HTML.
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
```

In `web/history.js`, delete the `const esc = ...` definition (three lines), since it now lives in `app.js`.

- [ ] **Step 2: Use `post` for every write**

In `web/app.js`:

```js
// in the flight card's stop button
      await post('/api/untrack', { key: e.target.dataset.key });
```

```js
// in the add-form submit handler, and again in window.quickTrack
    const f = await post('/api/track', { callsign: cs });
```

```js
// in the btn-refresh handler
    const r = await post('/api/poll');
```

In `web/history.js`:

```js
// in the delete handler
        await post('/api/history/delete', { id: f.id });
```

```js
// in the hist-form submit handler
    const f = await post(editing ? '/api/history/update' : '/api/history', {
      id: editingId,
      date: val('h-date'), from: val('h-from'), to: val('h-to'),
      airline: val('h-airline'), flight_number: val('h-flight'),
      aircraft: val('h-aircraft'), seat: val('h-seat'), notes: val('h-notes'),
    });
```

```js
// in the h-file change handler
    const r = await post('/api/history/import', { csv: await file.text() });
```

After this, `grep -n "method: 'POST'" web/*.js` must show only the one inside `post`.

- [ ] **Step 3: Escape everything the Live code puts into HTML**

In `web/app.js`, in `renderFlights`, replace the `card.innerHTML = ...` template with:

```js
    card.innerHTML = `
      <div class="top">
        <span class="cs">${esc(f.callsign)}</span>
        <span class="reg">${esc(f.registration || '')} ${esc(f.aircraft_type || '')}</span>
        <button class="x" title="Stop tracking" data-key="${esc(f.key)}">×</button>
      </div>
      <span class="phase ${esc(f.phase)}">${esc(f.phase.replace(/_/g, ' '))}${
        f.vertical && f.phase === 'airborne' ? ' · ' + esc(f.vertical) : ''}</span>
      <dl class="metrics">
        <div><dt>Alt</dt><dd>${fmt(f.altitude_ft)}</dd></div>
        <div><dt>Speed</dt><dd>${fmt(f.ground_speed_kt)}<span style="font-size:10px"> kt</span></dd></div>
        <div><dt>V/S</dt><dd>${f.vertical_rate_fpm ? fmt(f.vertical_rate_fpm) : '—'}</dd></div>
      </dl>`;
```

and the `layer.marker.bindPopup(...)` template with:

```js
    layer.marker.bindPopup(
      `<div class="pop"><b>${esc(f.callsign)}</b><br>
       ${esc(f.registration || '—')} · ${esc(f.aircraft_type || '—')}<br>
       ${esc(f.phase.replace(/_/g, ' '))} · ${esc(f.vertical)}<br>
       ${fmt(f.altitude_ft, ' ft')} · ${fmt(f.ground_speed_kt, ' kt')}<br>
       squawk ${esc(f.squawk || '—')} · seen ${fmt(f.stale_s, 's')} ago</div>`);
```

In `renderAlerts`, replace the `el.innerHTML = ...` template with:

```js
    el.innerHTML = `<span class="t">${String(t.getHours()).padStart(2, '0')}:${
      String(t.getMinutes()).padStart(2, '0')}</span>
      <span class="b"><span class="h">${esc(a.title)}</span>
      <span class="d">${esc(a.detail)}</span>
      <span class="f">${esc(a.flight)}</span></span>`;
```

In `renderLog`:

```js
    el.innerHTML = `<span class="c">${esc(l.callsign)}</span>
      <span style="color:var(--faint)">${esc(l.registration || '—')}</span>
      <span class="m">${fmt(l.max_altitude_ft, ' ft')} · ${fmt(l.max_speed_kt, ' kt')}</span>`;
```

In the `btn-nearby` handler, replace the `const html = ...` template with:

```js
      const html = `<div class="pop"><b>${esc(a.callsign)}</b><br>
        ${esc(a.registration || '—')} · ${esc(a.aircraft_type || '—')}<br>
        ${fmt(a.altitude_ft, ' ft')} · ${fmt(a.ground_speed_kt, ' kt')}<br>
        <button data-track="${esc(a.callsign)}">Track this</button></div>`;
```

In the `reg-form` handler, replace the `const html = ...` template with:

```js
    const html = `<div class="pop"><b>${esc(a.registration)}</b><br>
       flying as ${esc(a.callsign)} · ${esc(a.aircraft_type || '—')}<br>
       ${fmt(a.altitude_ft, ' ft')} · ${fmt(a.ground_speed_kt, ' kt')}<br>
       <button data-track="${esc(a.callsign)}">Track this</button></div>`;
```

The two popups used inline `onclick="quickTrack('...')"`, which let a crafted callsign run script. They now carry the callsign in `data-track`. Add one delegated handler directly below the `window.quickTrack = ...` definition:

```js
// Popups are built from HTML strings, so their Track button is wired here.
document.addEventListener('click', e => {
  const btn = e.target.closest('[data-track]');
  if (btn) window.quickTrack(btn.dataset.track);
});
```

After this, `grep -n "onclick" web/*.js` must print nothing.

- [ ] **Step 4: Boot from `/api/me` and gate the Live parts**

In `web/app.js`, add near the top, below `let lastFlights = [];`:

```js
let liveOn = false;
const meReady = api('/api/me');
```

Make `refresh` do nothing when Live is off, by adding one line at its start:

```js
async function refresh() {
  if (!liveOn) return;
  try {
```

Replace the last four lines of the file (`initMap();` through `setInterval(refresh, REFRESH_MS);`) with:

```js
function renderWho(me) {
  const who = $('who');
  who.innerHTML = `<span class="me">@${esc(me.username)}</span>` + (me.dev_users
    ? `<form id="dev-form"><input id="dev-user" placeholder="dev: switch user"
         spellcheck="false" autocapitalize="none"></form>` : '');
  if (!me.dev_users) return;
  $('dev-form').addEventListener('submit', async e => {
    e.preventDefault();
    try {
      await post('/dev/login', { username: $('dev-user').value });
      location.reload();
    } catch (err) { toast(err.message, true); }
  });
}

initMap();
// The globe needs WebGL and a CDN; if either is missing the flat map stays.
if (window.Globe3D) enableGlobe();
else window.addEventListener('globe-ready', enableGlobe, { once: true });

meReady.then(me => {
  renderWho(me);
  liveOn = me.live;
  document.body.classList.toggle('no-live', !me.live);
  if (!me.live) return;
  refresh();
  setInterval(refresh, REFRESH_MS);
}).catch(() => {
  $('pill-source').textContent = 'server unreachable';
  $('pill-source').className = 'pill bad';
});
```

- [ ] **Step 5: Generalise the tabs and the map route layer in `web/history.js`**

Replace the tabs section (from `// ---- tabs` through the two `addEventListener` lines) with:

```js
// -------------------------------------------------------------------- tabs
const TABS = ['history', 'social', 'live'].filter(t => $('tab-' + t));

function showTab(name) {
  for (const t of TABS) {
    $('pane-' + t).hidden = t !== name;
    $('tab-' + t).classList.toggle('on', t === name);
  }
  document.dispatchEvent(new CustomEvent('tab', { detail: name }));
}
for (const t of TABS) $('tab-' + t).addEventListener('click', () => showTab(t));
```

Replace `let routeLayer = null;` and the whole `routesToMap` function with:

```js
const mapLayers = {};

// Draw (or, with empty lists, clear) one named set of routes on the flat map.
function mapRoutes(key, routes, airports, colour) {
  if (typeof map === 'undefined' || !map) return;
  const layer = mapLayers[key] || (mapLayers[key] = L.layerGroup().addTo(map));
  layer.clearLayers();
  // Draw each route and airport in the neighbouring world copies too, so a
  // route that crosses the antimeridian still meets its far airport.
  for (const shift of [-360, 0, 360]) {
    for (const r of routes) {
      L.polyline(greatCircle(r.a, r.b).map(([la, lo]) => [la, lo + shift]),
                 { color: colour, weight: 1.6, opacity: 0.75,
                   interactive: false }).addTo(layer);
    }
    for (const a of airports) {
      L.circleMarker([a.lat, a.lon + shift],
                     { radius: 3.5, color: '#dff7fa', weight: 1,
                       fillColor: colour, fillOpacity: 1 })
        .bindTooltip(`${a.code} · ${a.name}`, { className: 'tag' })
        .addTo(layer);
    }
  }
}
```

In `drawRoutes`, replace the call `routesToMap([...routes.values()], [...airports.values()]);` with:

```js
  mapRoutes('mine', [...routes.values()], [...airports.values()], '#5fd0dd');
```

Leaflet's tooltip takes a string as HTML, and airport names come from the data file, so this stays as it is.

- [ ] **Step 6: Markup**

In `web/index.html`:

Replace the header block with:

```html
<header class="bar">
  <div class="brand"><span class="glyph">✈</span> WING<span class="dim">MATES</span></div>
  <div class="status live-only" id="status">
    <span class="pill" id="pill-source">connecting…</span>
    <span class="pill quiet" id="pill-tracked">0 tracked</span>
    <span class="pill quiet" id="pill-poll">—</span>
  </div>
  <div class="who" id="who"></div>
</header>
```

Change the Live tab button to carry the class:

```html
      <button role="tab" id="tab-live" class="live-only">Live</button>
```

Add an Export link beside Template:

```html
          <a class="link" href="/api/history/export.csv" download>Export</a>
          <a class="link" href="/api/history/template.csv" download>Template</a>
```

Add `class="live-only"` to `btn-nearby`, `btn-clear` and `btn-refresh`, and change the registration form's class to `class="reg live-only"`:

```html
      <button id="btn-nearby" class="live-only" title="Show aircraft around the map centre">Nearby</button>
      <button id="btn-clear" class="live-only" title="Hide nearby aircraft">Clear</button>
      <button id="btn-refresh" class="live-only" title="Poll the feed now">Poll now</button>
      <form id="reg-form" class="reg live-only">
```

- [ ] **Step 7: Styles**

In `web/style.css`, replace the rule `.status{margin-left:auto;...}` with:

```css
.status{margin-left:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.who{display:flex;gap:10px;align-items:center;font-family:var(--mono);font-size:12px;
  color:var(--muted)}
body.no-live .who{margin-left:auto}
.who input{width:150px;font-size:11px;padding:5px 8px}
body.no-live .live-only{display:none}
.link + .link{margin-left:12px}
```

- [ ] **Step 8: Check syntax**

Run: `node --check web/app.js && node --check web/history.js && echo ok`
Expected: `ok`

- [ ] **Step 9: Check in the browser**

Start the `wingmates-dev` launch configuration and open `http://localhost:8817`.

- The header shows `@you` and a "dev: switch user" box. No console errors.
- Add a flight ATL to LHR. It appears, with an arc. Edit it, then delete it.
- Click Export: a CSV downloads whose first line is the template header.
- Type `ann` in the switch box and press Enter: the page reloads as `@ann` with an empty log. Switch to `you`: the earlier state returns.
- Open the Live tab: tracking and Nearby still work, and "Track this" in a Nearby popup tracks the aircraft.
- Stop the server. Restart it with `WINGMATES_LIVE=0` added: the Live tab, the status pills and the Nearby, Clear, Poll now and registration controls are gone, and the network log shows no `/api/state` requests.

- [ ] **Step 10: Commit**

```bash
git add web/app.js web/history.js web/index.html web/style.css
git commit -m "Escape feed values, post JSON, and boot the page from /api/me

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Social tab and mate routes on the globe and map

**Files:**
- Create: `web/social.js`
- Modify: `web/globe.js`, `web/index.html`, `web/style.css`

**Interfaces:**
- Consumes: the social routes from Task 7; globals `$`, `api`, `post`, `esc`, `fmt`, `toast`, `meReady` from `app.js`; `mapRoutes` and the `tab` event from `history.js`.
- Produces: `Globe3D.setMateRoutes(routes, airports)` with the same argument shapes as `Globe3D.setRoutes`: `routes` is `[{a: [lat, lon], b: [lat, lon]}]`, `airports` is `[{lat, lon, code, name}]`. Passing two empty arrays clears the layer.

- [ ] **Step 1: Give the globe two route layers**

In `web/globe.js`, replace the block that starts at `let routeLine = null;` and ends at the closing brace of `function setRoutes(routes, airports) {...}` — keeping `arcSegments` exactly as it is in between — so the section reads:

```js
// ------------------------------------------------------------ flight history
// Two independent sets of routes: the user's own, and one mate's.
function routeLayer(colour, dotClass) {
  return { colour, dotClass, routes: [], line: null, dots: [] };
}
const layers = {
  mine: routeLayer('#5fd0dd', 'gdot'),
  mate: routeLayer('#f08a6b', 'gdot mate'),
};
```

then the existing `arcSegments` function, unchanged, then:

```js
function buildLine(layer) {
  if (layer.line) {
    scene.remove(layer.line);
    layer.line.geometry.dispose();
    layer.line.material.dispose();
    layer.line = null;
  }
  if (!layer.routes.length) return;
  const positions = [];
  for (const r of layer.routes) arcSegments(r.a, r.b, positions);
  const geo = new LineSegmentsGeometry();
  geo.setPositions(positions);
  // Opaque on purpose: segment ends overlap, and any blending beads the line.
  const mat = new LineMaterial({ color: layer.colour, linewidth: 1.8 });
  mat.resolution.set(w || 1, h || 1);
  layer.line = new LineSegments2(geo, mat);
  scene.add(layer.line);
}

// routes: [{a: [lat, lon], b: [lat, lon]}], one per distinct airport pair.
// airports: [{lat, lon, code, name}]
function setLayer(layer, routes, airports) {
  layer.routes = routes;
  buildLine(layer);
  for (const d of layer.dots) d.el.remove();
  layer.dots = airports.map(a => {
    const el = document.createElement('div');
    el.className = layer.dotClass;
    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = a.code;
    el.title = a.name || a.code;
    el.appendChild(tag);
    overlay.appendChild(el);
    return { el, lat: a.lat, lon: a.lon, pos: surface(a.lat, a.lon) };
  });
  dirty = true;
}
const setRoutes = (routes, airports) => setLayer(layers.mine, routes, airports);
const setMateRoutes = (routes, airports) => setLayer(layers.mate, routes, airports);
```

Then update the three other places that referred to the old variables.

In `resize`, replace `if (routeLine) routeLine.material.resolution.set(w, h);` with:

```js
  for (const layer of Object.values(layers)) {
    if (layer.line) layer.line.material.resolution.set(w, h);
  }
```

In `layout`, replace the opening line of the dots loop, `for (const m of dots) {`, with:

```js
  for (const m of [...layers.mine.dots, ...layers.mate.dots]) {
```

In the elevation `img.onload` handler, replace the two lines `for (const m of dots) m.pos = surface(m.lat, m.lon);` and `buildRoutes();` with:

```js
    for (const layer of Object.values(layers)) {
      for (const m of layer.dots) m.pos = surface(m.lat, m.lon);
      buildLine(layer);
    }
```

In the `window.Globe3D = {...}` object, add `setMateRoutes` after `setRoutes`:

```js
  setRoutes, setMateRoutes, flyTo, flyToRoute, getCenter, viewRadiusNm,
```

Run: `node --check web/globe.js && grep -n "routeLine\|routeData\|buildRoutes\|of dots" web/globe.js`
Expected: no syntax error, and the `grep` prints nothing.

- [ ] **Step 2: Markup**

In `web/index.html`, add the Social tab button between My flights and Live:

```html
      <button role="tab" id="tab-social">Social<span class="badge" id="social-badge" hidden></span></button>
```

Add the pane between `pane-history`'s closing `</div>` and `<div id="pane-live" hidden>`:

```html
    <div id="pane-social" hidden>
      <form class="add" id="find-form" autocomplete="off">
        <label for="find-user">Find a mate</label>
        <div class="row">
          <input id="find-user" placeholder="@username" spellcheck="false"
                 autocapitalize="none" aria-label="Username">
          <button type="submit" id="find-btn">Find</button>
        </div>
        <p class="hint" id="find-hint">Type their exact username.</p>
      </form>
      <div id="find-card" class="log"></div>

      <section id="req-section" hidden>
        <h2>Requests <span class="count" id="req-count">0</span></h2>
        <div id="req-list" class="log"></div>
      </section>

      <section>
        <h2>Mates <span class="count" id="mates-count">0</span></h2>
        <div id="board" class="log"></div>
        <p class="empty" id="mates-empty">No mates yet. Find one by username above.</p>
      </section>

      <section id="h2h" hidden></section>
    </div>
```

Add the script after `history.js`:

```html
<script defer src="/static/social.js"></script>
```

- [ ] **Step 3: Write `web/social.js`**

```js
'use strict';

// Social tab: find people by username, answer requests, compare wingspans.
// Shares $, api, post, esc, fmt, toast and meReady with app.js, and mapRoutes
// and the 'tab' event with history.js.

const EARTH_MI = 24901;
const MATE_COLOUR = '#f08a6b';

let social = null;          // last /api/social payload
let openMateId = null;      // the mate shown head-to-head, if any

const laps = mi => (mi / EARTH_MI).toFixed(1);

function avatar(p) {
  const url = p.picture_url || '';
  // Only https pictures are ever used as an image source.
  return url.startsWith('https://')
    ? `<img class="av" src="${esc(url)}" alt="" referrerpolicy="no-referrer">`
    : `<span class="av">${esc((p.name || p.username || '?').charAt(0).toUpperCase())}</span>`;
}

function person(p) {
  return `${avatar(p)}<span class="pn"><b>${esc(p.name)}</b>
    <span class="un">@${esc(p.username)}</span></span>`;
}

function button(label, cls, fn) {
  const b = document.createElement('button');
  b.textContent = label;
  if (cls) b.className = cls;
  b.addEventListener('click', e => { e.stopPropagation(); fn(b); });
  return b;
}

function note(text) {
  const s = document.createElement('span');
  s.className = 'st';
  s.textContent = text;
  return s;
}

function findHint(msg, bad) {
  const h = $('find-hint');
  h.className = 'hint' + (bad ? ' error' : '');
  h.textContent = msg;
}

// ------------------------------------------------------------------- data
async function loadSocial() {
  try {
    renderSocial(await api('/api/social'));
  } catch (e) {
    findHint(`Could not load your mates: ${e.message}`, true);
  }
}

// Run one action, then refresh the page's state and any open lookup card.
async function act(path, body, done) {
  try {
    await post(path, body);
    if (done) toast(done);
  } catch (e) {
    toast(e.message, true);
  }
  await loadSocial();
  const shown = $('find-card').dataset.username;
  if (shown) lookup(shown);
}

// ----------------------------------------------------------------- lookup
async function lookup(username) {
  const box = $('find-card');
  try {
    renderCard(await api('/api/users/lookup?username=' + encodeURIComponent(username)));
    findHint('Type their exact username.');
  } catch (e) {
    box.innerHTML = '';
    delete box.dataset.username;
    findHint(e.message, true);
  }
}

function renderCard(p) {
  const box = $('find-card');
  box.innerHTML = '';
  box.dataset.username = p.username;
  const row = document.createElement('div');
  row.className = 'logrow prow';
  row.innerHTML = person(p);
  if (p.relation === 'self') {
    row.append(note('This is you'));
  } else if (p.relation === 'mate') {
    row.append(note('Already mates'));
  } else if (p.relation === 'requested') {
    row.append(note('Requested'),
               button('Cancel', 'quiet', () => act(`/api/mates/${p.id}/cancel`)));
  } else if (p.relation === 'incoming') {
    row.append(button('Accept', '', () => act(`/api/mates/${p.id}/accept`, {},
                      `You and @${p.username} are mates.`)));
  } else {
    row.append(button('Add mate', '', () => act('/api/mates/request',
                      { username: p.username })));
  }
  box.appendChild(row);
}

$('find-form').addEventListener('submit', e => {
  e.preventDefault();
  const q = $('find-user').value.trim();
  if (q) lookup(q);
});

// ----------------------------------------------------------------- render
function renderSocial(d) {
  social = d;

  const badge = $('social-badge');
  badge.hidden = d.incoming.length === 0;
  badge.textContent = d.incoming.length;

  const reqs = $('req-list');
  reqs.innerHTML = '';
  $('req-section').hidden = d.incoming.length + d.outgoing.length === 0;
  $('req-count').textContent = d.incoming.length + d.outgoing.length;
  for (const p of d.incoming) {
    const row = document.createElement('div');
    row.className = 'logrow prow';
    row.innerHTML = person(p);
    row.append(
      button('Accept', '', () => act(`/api/mates/${p.id}/accept`, {},
             `You and @${p.username} are mates.`)),
      button('Decline', 'quiet', () => act(`/api/mates/${p.id}/decline`)));
    reqs.appendChild(row);
  }
  for (const p of d.outgoing) {
    const row = document.createElement('div');
    row.className = 'logrow prow';
    row.innerHTML = person(p);
    row.append(note('Requested'),
               button('Cancel', 'quiet', () => act(`/api/mates/${p.id}/cancel`)));
    reqs.appendChild(row);
  }

  $('mates-count').textContent = d.mates.length;
  $('mates-empty').style.display = d.mates.length ? 'none' : 'block';
  const board = $('board');
  board.innerHTML = '';
  const everyone = [{ ...d.me, isMe: true }, ...d.mates]
    .sort((a, b) => b.stats.distance_mi - a.stats.distance_mi);
  everyone.forEach((p, i) => {
    const s = p.stats;
    const row = document.createElement('div');
    row.className = 'logrow prow brow' + (p.isMe ? ' me' : '')
                  + (p.id === openMateId ? ' open' : '');
    row.innerHTML = `<span class="rank">${i + 1}</span>${person(p)}
      <span class="ws">${fmt(s.distance_mi)}<small>mi</small></span>
      <span class="sub">${laps(s.distance_mi)}× around the Earth ·
        ${fmt(s.countries)} countries · ${fmt(s.airports)} airports</span>`;
    if (!p.isMe) row.addEventListener('click', () => toggleMate(p.id));
    board.appendChild(row);
  });

  if (openMateId === null) return;
  if (d.mates.some(m => m.id === openMateId)) renderH2H();
  else closeMate();
}

// ----------------------------------------------------------- head to head
const H2H_ROWS = [['Wingspan', 'distance_mi', ' mi'], ['Flights', 'flights', ''],
                  ['Airports', 'airports', ''], ['Countries', 'countries', '']];

function renderH2H() {
  const mate = social.mates.find(m => m.id === openMateId);
  const me = social.me.stats, them = mate.stats;
  const box = $('h2h');
  box.hidden = false;
  box.innerHTML = `<h2>You vs @${esc(mate.username)}</h2>
    <table class="h2h">${H2H_ROWS.map(([label, key, unit]) => `<tr>
      <td class="${me[key] > them[key] ? 'lead' : ''}">${fmt(me[key], unit)}</td>
      <th>${label}</th>
      <td class="${them[key] > me[key] ? 'lead' : ''}">${fmt(them[key], unit)}</td>
    </tr>`).join('')}</table>`;
  // Removing takes two clicks, like deleting a flight.
  box.appendChild(button('Remove mate', 'quiet', b => {
    if (b.dataset.armed !== '1') {
      b.dataset.armed = '1';
      b.textContent = `Remove @${mate.username}?`;
      setTimeout(() => { b.dataset.armed = ''; b.textContent = 'Remove mate'; }, 3000);
      return;
    }
    act(`/api/mates/${mate.id}/remove`, {}, `Removed @${mate.username}.`);
  }));
}

function drawMate(routes) {
  const arcs = routes.map(r => ({ a: [r.from.lat, r.from.lon],
                                  b: [r.to.lat, r.to.lon] }));
  const airports = new Map();
  for (const r of routes) {
    for (const a of [r.from, r.to]) {
      airports.set(a.iata, { lat: a.lat, lon: a.lon, code: a.iata,
                             name: `${a.name} · ${a.city}` });
    }
  }
  if (window.Globe3D) window.Globe3D.setMateRoutes(arcs, [...airports.values()]);
  mapRoutes('mate', arcs, [...airports.values()], MATE_COLOUR);
}

async function toggleMate(id) {
  if (openMateId === id) return closeMate();
  openMateId = id;
  renderSocial(social);
  try {
    const d = await api(`/api/mates/${id}/routes`);
    if (openMateId === id) drawMate(d.routes);
  } catch (e) {
    toast(e.message, true);
  }
}

function closeMate() {
  openMateId = null;
  $('h2h').hidden = true;
  drawMate([]);
  if (social) renderSocial(social);
}

// ------------------------------------------------------------------- boot
document.addEventListener('tab', e => {
  if (e.detail === 'social') loadSocial();
  else if (openMateId !== null) closeMate();
});

// Load once at start so the tab shows its request count.
meReady.then(loadSocial).catch(() => {});
```

- [ ] **Step 4: Styles**

The tab bar was styled for exactly two buttons. It now has three, and the last one can be hidden when Live is off, so the rounding moves to the container. In `web/style.css`, replace these three existing rules:

```css
.tabs{display:flex;margin-bottom:18px}
.tabs button:first-child{border-radius:3px 0 0 3px}
.tabs button:last-child{border-radius:0 3px 3px 0;border-left:none}
```

with:

```css
.tabs{display:flex;margin-bottom:18px;border-radius:3px;overflow:hidden}
.tabs button{border-radius:0}
.tabs button + button{border-left:none}
```

Leave the other two `.tabs button` rules (the base style and `.on`) as they are, and keep the new `.tabs button{border-radius:0}` line after the base rule.

Then add, before the `.mapwrap{flex:1;` rule:

```css
.badge{display:inline-block;margin-left:6px;min-width:16px;padding:0 4px;border-radius:8px;
  background:var(--accent);color:var(--bg);font-size:10px;line-height:16px;letter-spacing:0}
.badge[hidden]{display:none}
.prow{align-items:center;gap:10px;font-family:var(--sans);font-size:13px}
.prow .av{width:28px;height:28px;border-radius:50%;flex:none;object-fit:cover;
  display:inline-flex;align-items:center;justify-content:center;
  background:var(--accent-dim);color:var(--accent);font-family:var(--mono);font-size:12px}
.prow .pn{display:flex;flex-direction:column;min-width:0;line-height:1.3;margin-right:auto}
.prow .pn b{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.prow .un{font-family:var(--mono);font-size:10.5px;color:var(--faint)}
.prow .st{font-family:var(--mono);font-size:10.5px;color:var(--muted)}
.prow button{padding:6px 10px}
button.quiet{background:none;border-color:var(--line);color:var(--muted)}
button.quiet:hover{background:var(--panel-2);color:var(--ink)}
.brow{flex-wrap:wrap;row-gap:2px;cursor:pointer}
.brow.me{cursor:default;border-color:#17414a}
.brow.open{border-color:#f08a6b}
.brow .rank{font-family:var(--mono);font-size:11px;color:var(--faint);width:14px}
.brow .ws{font-family:var(--mono);font-size:15px;font-variant-numeric:tabular-nums}
.brow .ws small{font-size:10.5px;color:var(--muted);margin-left:3px}
.brow .sub{flex-basis:100%;padding-left:24px;color:var(--faint);font-family:var(--mono);
  font-size:10.5px}
table.h2h{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:13px;
  margin-bottom:12px;font-variant-numeric:tabular-nums}
table.h2h th{font-weight:400;font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;
  color:var(--faint);text-align:center;padding:7px 6px}
table.h2h td{width:38%;padding:7px 6px;color:var(--muted)}
table.h2h td:first-child{text-align:right}
table.h2h td.lead{color:var(--ink);font-weight:600}
table.h2h td:first-child.lead{color:var(--accent)}
table.h2h td:last-child.lead{color:#f08a6b}
.gdot.mate{background:#fde3da;box-shadow:0 0 6px 2px rgba(240,138,107,.7)}
```


- [ ] **Step 5: Check syntax**

Run: `node --check web/social.js && node --check web/globe.js && echo ok`
Expected: `ok`

- [ ] **Step 6: Check in the browser**

Start `wingmates-dev` and open `http://localhost:8817`. Delete `.devdata/` first for a clean start.

1. As `@you`, add ATL to LHR. Switch to `ann`; add ATL to NRT and NRT to ATL (two flights, one route). Switch to `bob`; add JFK to LHR.
2. As `@bob`, open Social. Type `@Ann ` and press Find: a card for `@ann` with **Add mate**. Press it: the card reads **Requested** with **Cancel**, and Requests lists `@ann`.
3. Type `nobody`: the hint reads "no one has that username" in red.
4. Switch to `ann`. The Social tab shows a badge reading `1`. Open it and press **Accept**: a toast confirms, the badge clears, and the Mates list shows two rows ranked by miles with `@ann` first.
5. Click the `@bob` row: a "You vs @bob" panel appears with the larger number highlighted in each row, and one coral JFK to LHR arc is drawn on the globe next to the teal ATL to NRT arc. Switch to Map: both arcs are there in the same colours.
6. Click `@bob` again: the panel and the coral arc go away. Open it again, then click the My flights tab: the coral arc goes away.
7. In the browser's network log, open the `/api/social` and `/api/mates/<id>/routes` responses. Neither contains `date`, `airline`, `seat` or `notes`.
8. Open the panel, press **Remove mate** twice: the Mates list returns to one row. Switch to `bob`: his list is also back to one row.
9. No console errors at any point.

- [ ] **Step 7: Commit**

```bash
git add web/social.js web/globe.js web/index.html web/style.css
git commit -m "Add the Social tab with wingspan comparison and mate routes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: README and final verification against real data

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the README**

Replace the opening block (from the title down to the test command block) with:

````markdown
# Wingmates — your flight history on a globe, with your mates

Three things in one app, sharing one map:

- **My flights** — log the flights you've taken (by hand or CSV) and see them
  as arcs on a 3D globe, with totals for flights, miles, airports and countries.
- **Social** — find people by username, become mates, and compare wingspans.
- **Live** — track a real aircraft right now from ADS-B data, with a state
  machine that derives departure/landing/descent and an alert feed.

No API key and no account. The browser loads its map libraries and textures
from public CDNs, so it needs an internet connection.

```
cd wingmates
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py
```

Opens `http://127.0.0.1:8817`. Press `ctrl-c` to stop. Needs Python 3.11+.

```
.venv/bin/python run.py --port 9000     # different port
.venv/bin/python run.py --no-browser    # don't auto-open
.venv/bin/python -m unittest discover -s tests -t .   # offline tests
```

There is no sign-in yet: on your own machine every request acts as one local
user, `@you`. Google sign-in and hosting are the next two steps.

### Settings

| Variable | Default | Effect |
|---|---|---|
| `WINGMATES_LIVE` | `1` | `0` turns off the live tracker and hides the Live tab. |
| `WINGMATES_DEV_USERS` | `0` | `1` adds a box in the header to switch between made-up users, for trying the Social tab. Never enable this on a server others can reach. |
| `WINGMATES_DATA_DIR` | `~/.wingmates` | Where `flights.db` and `state.json` live. |
````

Add this section after the "My flights" section:

```markdown
## Social

| | |
|---|---|
| **Find a mate** | Type someone's exact username. There is no browsing or partial search. |
| **Requests** | Adding someone sends a request they accept or decline. Declining is silent. |
| **Wingspan** | Total great-circle miles flown, also shown as times around the Earth. Mates are ranked by it. |
| **Head to head** | Click a mate to compare wingspan, flights, airports and countries, and to draw their routes on the globe in coral beside yours. |

A mate sees your totals and your distinct routes. They never see dates,
airlines, flight numbers, seats, notes, or how often you flew a route.
```

In the "My flights" table, change the Import CSV row's first cell to `**Import / export CSV**` and append to its text: ` Export downloads all your flights in the same columns.`

In the Layout block, remove the `fc/server.py` line and add:

```
fc/config.py            settings from environment variables
fc/db.py                SQLite schema and migration
fc/users.py             user records and username rules
fc/mates.py             mate requests, pairs, and what a mate may see
fc/webapp.py            Flask app: every HTTP route
web/social.js           Social tab
requirements.txt        Flask
```

In the Layout block, change the `tests/` line to `tests/                  offline tests — no network required`.

In the API block, add:

```
GET  /api/me                         the current user and feature flags
GET  /api/history/export.csv         your flights as CSV
GET  /api/social                     you, your mates with stats, pending requests
GET  /api/users/lookup?username=     one person's card
POST /api/mates/request {username}   send a request
POST /api/mates/<id>/accept | decline | cancel | remove
GET  /api/mates/<id>/routes          one mate's distinct routes
```

In the "Not built yet" section, replace the text with: `Sign-in and hosting. Until then it runs for one person on one machine, with made-up users available for trying the Social tab. Importing from calendar events or email confirmations is also not built.`

- [ ] **Step 2: Run the full test suite**

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: `OK`. Note the count it prints.

- [ ] **Step 3: Migrate the real data and confirm nothing was lost**

Before starting, record what is there:

```bash
sqlite3 ~/.wingmates/flights.db "SELECT date, origin, dest FROM flights ORDER BY date"
```

Start the `wingmates` launch configuration (the real data directory) and open `http://localhost:8817`.

- My flights lists exactly the flights recorded above, with the same totals as before.
- The header shows `@you`. The Live tab shows the same tracked flights as before.
- `ls ~/.wingmates` now includes `flights.db.pre-users.bak`.
- Stop and start the server again: the flights are unchanged and no second backup appears.

If any flight is missing, stop, restore with `cp ~/.wingmates/flights.db.pre-users.bak ~/.wingmates/flights.db`, and investigate before going further.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "Document the Social tab, settings and virtualenv setup

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
