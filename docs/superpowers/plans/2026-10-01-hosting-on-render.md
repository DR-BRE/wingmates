# Hosting on Render Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put Wingmates on the internet at a Render web address, with sign-in on, so friends can use it.

**Architecture:** One Docker container running gunicorn with a single worker process, its SQLite file on a Render persistent disk mounted at `/data`. A new entry point, `fc/wsgi.py`, builds the app from environment variables and refuses to start without sign-in. Render deploys the `main` branch from GitHub using `render.yaml`. Before going public, the plan also closes the deferred items from the sign-in review that matter on a shared site.

**Tech Stack:** Python 3.13 (container), Flask, gunicorn, SQLite, Docker, Render Blueprint (`render.yaml`).

**Spec:** `docs/superpowers/specs/2026-10-01-mates-and-wingspans-design.md`

This plan is build step 3 of the spec. **Out of scope:** a custom domain, email or calendar import, blocking and reporting, moving off SQLite.

## Global Constraints

- The hosted app runs exactly one gunicorn worker process (`--workers 1`), with threads. SQLite on a local disk cannot have several server processes writing.
- The hosted entry point never starts the live tracker, whatever `WINGMATES_LIVE` says.
- The hosted entry point refuses to start unless `WINGMATES_AUTH=google`.
- `GET /healthz` reveals nothing about any user, needs no sign-in, and answers whatever `Host` header the caller sends. Every other route keeps the host allow-list.
- The container listens on `0.0.0.0` at `$PORT`, default `10000`.
- The data directory in the container is `/data`. Nothing outside it is expected to survive a deploy.
- Secrets reach the container only as environment variables set in Render. None is written into `render.yaml`, the `Dockerfile`, or any committed file.
- Signing out ends every session of that account, on every device.
- Schema version becomes 2. A version 1 database is upgraded in place without losing rows.
- New dependency: `gunicorn>=23,<27`. Container base image: `python:3.13-slim`.
- All tests are offline. Run them with `.venv/bin/python -m unittest discover -s tests -t .`
- End every commit message with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

Each of these has a test in the task named.

1. **Render's health checker calls with an internal `Host` header.** If `/healthz` were behind the host allow-list it would get 403, and no deploy would ever go live. Expected: 200. Task 1.
2. **A deploy where `WINGMATES_AUTH` was forgotten.** Expected: the server refuses to start, not a public site where every visitor shares one account. Task 2.
3. **People who are signed in when the session change ships.** Their cookie has no session epoch. Expected: they are asked to sign in again, with no error page. Task 3.
4. **A redeploy.** Expected: accounts and flights are still there, and people are still signed in. Task 2.
5. **The database file is missing or unreadable while the server is up.** Expected: `/healthz` answers 503 so Render can tell, and the check itself does not create a new empty database. Task 1.

## File Structure

| File | Responsibility |
|---|---|
| `fc/webapp.py` (modify) | `/healthz`; session epoch in the current-user check; clears stale sign-in state. |
| `fc/config.py` (modify) | Base URL falls back to Render's hostname. |
| `fc/hosted.py` (new) | `build()`: the app for a hosted server, with its safety checks. |
| `fc/wsgi.py` (new) | Two lines: the object gunicorn imports. |
| `fc/db.py` (modify) | Schema v2 (`session_epoch`), v1 upgrade, file permissions. |
| `fc/users.py` (modify) | Session epoch methods; conflict-safe Google upsert. |
| `fc/auth.py` (modify) | Race-safe `persistent_key`. |
| `Dockerfile`, `.dockerignore`, `render.yaml` (new) | The container and the Render service. |
| `requirements.txt` (modify) | Adds gunicorn. |
| `docs/deploy-render.md` (new), `README.md`, `docs/google-sign-in-setup.md` (modify) | Deploy guide. |
| `tests/test_webapp.py`, `test_signin.py`, `test_config.py`, `test_db.py`, `test_users.py`, `test_auth.py` (modify) | Tests for each change. |

---

### Task 1: Health check

**Files:**
- Modify: `fc/webapp.py`, `tests/test_webapp.py`, `tests/test_signin.py`

**Interfaces:**
- Consumes: `Config.db_path`.
- Produces: `GET /healthz` → `200 {"ok": true}` when the database can be read, `503 {"ok": false}` when it cannot. Exempt from the host allow-list and from sign-in.

- [ ] **Step 1: Create the branch**

```bash
cd ~/flighty-clone
git checkout -b hosting
git add docs/superpowers && git commit -m "Add the hosting plan and spec amendments

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_webapp.py`, above the `if __name__` line:

```python
class TestHealth(WebCase):
    INTERNAL = "http://10.214.3.7:10000"

    def test_it_answers_whatever_host_the_checker_uses(self):
        r = self.client.get("/healthz", base_url=self.INTERNAL)
        self.assertEqual((r.status_code, r.get_json()), (200, {"ok": True}))
        # Only the health check is exempt from the host allow-list.
        self.assertEqual(
            self.client.get("/api/me", base_url=self.INTERNAL).status_code, 403)
        self.assertEqual(self.client.get("/", base_url=self.INTERNAL).status_code,
                         403)

    def test_it_reports_a_missing_database_without_creating_one(self):
        (self.dir / "flights.db").unlink()
        r = self.client.get("/healthz")
        self.assertEqual((r.status_code, r.get_json()), (503, {"ok": False}))
        self.assertFalse((self.dir / "flights.db").exists())

    def test_it_only_answers_get(self):
        self.assertEqual(self.post("/healthz").status_code, 405)
```

Add to `TestSignedOut` in `tests/test_signin.py`:

```python
    def test_the_health_check_needs_no_sign_in(self):
        r = self.client.get("/healthz", base_url="http://10.214.3.7:10000")
        self.assertEqual((r.status_code, r.get_json()), (200, {"ok": True}))
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_webapp.TestHealth tests.test_signin.TestSignedOut -v 2>&1 | tail -8`
Expected: failures with `403 != 200` and `404 != 503`.

- [ ] **Step 4: Implement**

In `fc/webapp.py`, add to the imports:

```python
import sqlite3
from contextlib import closing
```

At the very start of `guard()`, before the host check, add:

```python
        if request.path == "/healthz":
            # The host's health checker calls from inside its own network,
            # under a name this app does not know. The route reveals nothing.
            return None
```

Add this route directly above `@app.get("/")`:

```python
    @app.get("/healthz")
    def healthz():
        """Can the database be read? Opened read-only, so checking a missing
        file does not create an empty one in its place."""
        try:
            with closing(sqlite3.connect(f"file:{config.db_path}?mode=ro",
                                         uri=True)) as db:
                db.execute("SELECT 1 FROM users LIMIT 1")
        except sqlite3.Error:
            return jsonify(ok=False), 503
        return jsonify(ok=True)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add fc/webapp.py tests/test_webapp.py tests/test_signin.py
git commit -m "Add a health check that is exempt from the host allow-list

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The hosted entry point

**Files:**
- Create: `fc/hosted.py`, `fc/wsgi.py`
- Modify: `fc/config.py`, `requirements.txt`, `tests/test_config.py`, `tests/test_signin.py`

**Interfaces:**
- Consumes: `Config.from_env`, `create_app`.
- Produces:
  - `Config.from_env` uses `WINGMATES_BASE_URL` if set, else `https://` + `RENDER_EXTERNAL_HOSTNAME` if set, else the localhost default.
  - `fc.hosted.build(env=None, sign_in=None) -> Flask` — raises `RuntimeError` unless the configuration has `auth == "google"`; never passes a tracker.
  - `fc.wsgi.app` — `build()` called with the real environment; the object gunicorn serves.

- [ ] **Step 1: Add gunicorn**

```bash
printf 'Flask>=3.1,<4\nAuthlib>=1.3,<2\nrequests>=2.31,<3\ngunicorn>=23,<27\n' > requirements.txt
.venv/bin/python -m pip install -q -r requirements.txt
.venv/bin/gunicorn --version
```

Expected: a gunicorn version line.

- [ ] **Step 2: Write the failing tests**

Add to `TestBaseUrl` in `tests/test_config.py`:

```python
    def test_on_render_it_defaults_to_the_services_own_address(self):
        render = {"RENDER_EXTERNAL_HOSTNAME": "wingmates-x1y2.onrender.com"}
        self.assertEqual(Config.from_env(render).base_url,
                         "https://wingmates-x1y2.onrender.com")
        both = {**render, "WINGMATES_BASE_URL": "https://wingmates.example"}
        self.assertEqual(Config.from_env(both).base_url,
                         "https://wingmates.example")
```

Add to `tests/test_signin.py`, above the `if __name__` line, and add `from fc.hosted import build` to its imports:

```python
class TestHosted(unittest.TestCase):

    def setUp(self):
        self.dir, self.airports, _, _ = stores(self)
        self.google = FakeSignIn()
        self.env = {"WINGMATES_AUTH": "google", "WINGMATES_DATA_DIR": str(self.dir),
                    "GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "secret",
                    "SECRET_KEY": "a-fixed-key", "WINGMATES_BASE_URL": BASE}

    def signed_in_cookie(self, app):
        client = app.test_client()
        self.google.profile = BRETT
        client.get(client.get("/auth/login").headers["Location"])
        return client.get_cookie("session").value

    def test_it_refuses_to_start_without_sign_in(self):
        for env in ({"WINGMATES_DATA_DIR": str(self.dir)},
                    {"WINGMATES_AUTH": "local", "WINGMATES_DATA_DIR": str(self.dir)}):
            with self.assertRaises(RuntimeError) as cm:
                build(env)
            self.assertIn("WINGMATES_AUTH=google", str(cm.exception))

    def test_it_builds_a_signed_out_app_that_passes_its_health_check(self):
        client = build(self.env, sign_in=self.google).test_client()
        self.assertEqual(client.get("/healthz").get_json(), {"ok": True})
        self.assertEqual(client.get("/").headers["Location"], "/login")
        self.assertEqual(client.get("/api/me").status_code, 401)

    def test_it_never_runs_the_live_tracker(self):
        app = build({**self.env, "WINGMATES_LIVE": "1"}, sign_in=self.google)
        client = app.test_client()
        client.set_cookie("session", self.signed_in_cookie(app))
        client.post("/api/username", json={"username": "brett"}, headers=ORIGIN)
        self.assertFalse(client.get("/api/me").get_json()["live"])
        self.assertEqual(client.get("/api/state").status_code, 404)

    def test_people_and_their_flights_survive_a_redeploy(self):
        first = build(self.env, sign_in=self.google)
        cookie = self.signed_in_cookie(first)
        before = first.test_client()
        before.set_cookie("session", cookie)
        before.post("/api/username", json={"username": "brett"}, headers=ORIGIN)
        before.post("/api/history", headers=ORIGIN,
                    json={"date": "2024-03-09", "from": "ATL", "to": "LHR"})

        # A redeploy is a new process over the same disk and the same settings.
        after = build(self.env, sign_in=self.google).test_client()
        after.set_cookie("session", cookie)
        self.assertEqual(after.get("/api/me").get_json()["username"], "brett")
        self.assertEqual(len(after.get("/api/history").get_json()["flights"]), 1)
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_signin tests.test_config 2>&1 | tail -6`
Expected: `ModuleNotFoundError: No module named 'fc.hosted'`, and one failure in `TestBaseUrl`.

- [ ] **Step 4: Implement**

In `fc/config.py`, add above `_google_client`:

```python
def _base_url(env: Mapping[str, str]) -> str:
    """The address people use. On Render the service's own hostname is known,
    so nothing needs setting until a custom domain is added."""
    explicit = env.get("WINGMATES_BASE_URL")
    if explicit:
        return explicit
    render_host = env.get("RENDER_EXTERNAL_HOSTNAME")
    return f"https://{render_host}" if render_host else DEFAULT_BASE_URL
```

and in `from_env` replace the line `base_url=env.get("WINGMATES_BASE_URL") or DEFAULT_BASE_URL,` with:

```python
            base_url=_base_url(env),
```

Create `fc/hosted.py`:

```python
"""The app as a hosted server runs it.

Kept apart from run.py because the two have different duties. run.py serves
one person on their own machine. This serves strangers, so it insists on
sign-in and never runs the live tracker, which polls free community feeds on
behalf of whoever is at the keyboard.
"""
from __future__ import annotations

from collections.abc import Mapping

from flask import Flask

from .config import Config
from .webapp import create_app


def build(env: Mapping[str, str] | None = None, sign_in=None) -> Flask:
    config = Config.from_env(env)
    if config.auth != "google":
        raise RuntimeError(
            "a hosted Wingmates needs WINGMATES_AUTH=google: without sign-in, "
            "every visitor would share one account")
    return create_app(config, tracker=None, sign_in=sign_in)
```

Create `fc/wsgi.py`:

```python
"""What gunicorn serves: `gunicorn fc.wsgi:app`."""
from .hosted import build

app = build()
```

`fc/wsgi.py` builds the app when imported, so no test imports it. It is exercised by the real gunicorn run in Task 5.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt fc/config.py fc/hosted.py fc/wsgi.py tests/test_config.py tests/test_signin.py
git commit -m "Add the hosted entry point

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Signing out ends every session

**Files:**
- Modify: `fc/db.py`, `fc/users.py`, `fc/webapp.py`, `tests/test_db.py`, `tests/test_users.py`, `tests/test_signin.py`

A session cookie is signed, not stored, so today a copy of a cookie taken before sign-out keeps working until it expires. Each account gets a counter, its session epoch. A cookie records the epoch it was issued under and is valid only while that still matches. Signing out raises the epoch.

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - Schema version 2: `users.session_epoch INTEGER NOT NULL DEFAULT 0`. `db.init` upgrades a version 1 database in place.
  - `Users.session_epoch(user_id: int) -> int | None`
  - `Users.for_session(user_id: int, epoch) -> dict | None` — the user, only if `epoch` equals their current epoch.
  - `Users.end_sessions(user_id: int) -> None` — raises the epoch by one.
  - The session cookie gains an `epoch` entry beside `uid`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py`, above the `if __name__` line:

```python
# The users table exactly as schema version 1 created it.
V1_USERS = """
CREATE TABLE users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    google_sub  TEXT UNIQUE,
    username    TEXT UNIQUE,
    email       TEXT,
    name        TEXT NOT NULL,
    picture_url TEXT,
    created_at  TEXT NOT NULL
)"""


class TestUpgradeFromV1(DbCase):

    def v1(self):
        with closing(sqlite3.connect(self.path)) as raw, raw:
            for ddl in (V1_USERS, db._FLIGHTS, db._REQUESTS, db._MATES):
                raw.execute(ddl)
            raw.execute("INSERT INTO users (google_sub, username, name, created_at)"
                        " VALUES ('g-1', 'brett', 'Brett', 't')")
            raw.execute("INSERT INTO flights (user_id, date, origin, dest,"
                        " distance_km, created_at) VALUES (1, '2026-09-17',"
                        " 'SEA', 'KEF', 5811.0, 't')")
            raw.execute("PRAGMA user_version = 1")

    def test_accounts_and_flights_are_kept_and_the_epoch_starts_at_zero(self):
        self.v1()
        db.init(self.path)
        with closing(db.connect(self.path)) as c:
            user = c.execute("SELECT * FROM users").fetchone()
            self.assertEqual((user["username"], user["session_epoch"]),
                             ("brett", 0))
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM flights").fetchone()[0], 1)
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_upgrading_twice_changes_nothing(self):
        self.v1()
        db.init(self.path)
        db.init(self.path)
        with closing(db.connect(self.path)) as c:
            cols = [r["name"] for r in c.execute("PRAGMA table_info(users)")]
        self.assertEqual(cols.count("session_epoch"), 1)

    def test_a_fresh_database_has_the_column(self):
        db.init(self.path)
        with closing(db.connect(self.path)) as c, c:
            uid = db.ensure_local_user(c)
            self.assertEqual(c.execute(
                "SELECT session_epoch FROM users WHERE id = ?",
                (uid,)).fetchone()[0], 0)
```

Add to `tests/test_users.py`, above the `if __name__` line:

```python
class TestSessionEpoch(UsersCase):

    def setUp(self):
        super().setUp()
        self.uid = self.users.create("Ann", "ann")["id"]

    def test_a_session_is_valid_only_under_the_current_epoch(self):
        self.assertEqual(self.users.session_epoch(self.uid), 0)
        self.assertEqual(self.users.for_session(self.uid, 0)["username"], "ann")
        self.users.end_sessions(self.uid)
        self.assertEqual(self.users.session_epoch(self.uid), 1)
        self.assertIsNone(self.users.for_session(self.uid, 0))
        self.assertEqual(self.users.for_session(self.uid, 1)["id"], self.uid)

    def test_a_missing_or_malformed_epoch_never_matches(self):
        for bad in (None, "0", 0.5, [0]):
            self.assertIsNone(self.users.for_session(self.uid, bad), repr(bad))
        self.assertIsNone(self.users.for_session(999, 0))
        self.assertIsNone(self.users.session_epoch(999))

    def test_the_epoch_is_not_part_of_the_public_user(self):
        self.assertNotIn("session_epoch", self.users.for_session(self.uid, 0))

    def test_ending_one_persons_sessions_leaves_others_alone(self):
        bob = self.users.create("Bob", "bob")["id"]
        self.users.end_sessions(self.uid)
        self.assertEqual(self.users.session_epoch(bob), 0)
```

Add to `TestSessions` in `tests/test_signin.py`:

```python
    def test_signing_out_ends_every_session_of_the_account(self):
        phone, _ = self.sign_in(username="brett")
        laptop, _ = self.sign_in()
        copied = self.app.test_client()
        copied.set_cookie("session", phone.get_cookie("session").value)
        ann, _ = self.sign_in(ANN, username="ann")
        for client in (phone, laptop, copied):
            self.assertEqual(client.get("/api/me").status_code, 200)

        self.post("/auth/logout", client=phone)
        for client in (phone, laptop, copied):
            self.assertEqual(client.get("/api/me").status_code, 401)
        self.assertEqual(ann.get("/api/me").get_json()["username"], "ann")

        again, _ = self.sign_in()
        self.assertEqual(again.get("/api/me").get_json()["username"], "brett")
        self.assertEqual(copied.get("/api/me").status_code, 401)

    def test_a_cookie_from_before_session_epochs_is_asked_to_sign_in(self):
        client, _ = self.sign_in(username="brett")
        uid = client.get("/api/me").get_json()["id"]
        old = self.app.test_client()
        with old.session_transaction() as s:
            s["uid"] = uid                      # no epoch, as issued before
        r = old.get("/api/me")
        self.assertEqual((r.status_code, r.get_json()),
                         (401, {"error": "sign in required"}))
        self.assertEqual(old.get("/").headers["Location"], "/login")

    def test_signing_out_while_signed_out_is_harmless(self):
        self.assertEqual(self.post("/auth/logout").get_json(), {"ok": True})
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_db tests.test_users tests.test_signin 2>&1 | tail -6`
Expected: errors naming `session_epoch`, `for_session` and failures of the new sign-in tests.

- [ ] **Step 3: Implement the schema**

In `fc/db.py`, set `SCHEMA_VERSION = 2`, and in `_USERS` add a line after `picture_url TEXT,`:

```python
    session_epoch INTEGER NOT NULL DEFAULT 0,
```

Replace the whole `init` function with:

```python
def init(path: Path) -> None:
    """Create the schema, or bring an older database up to it. A database
    already at the current version is left untouched.

    Version 0 is either empty or the single-user format (a bare flights
    table). Version 1 lacks users.session_epoch."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as db:
        version = _version(db)
        if version >= SCHEMA_VERSION:
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
```

- [ ] **Step 4: Implement the user methods**

In `fc/users.py`, add to `Users`, after `get`:

```python
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
```

- [ ] **Step 5: Use the epoch in the web layer**

In `fc/webapp.py`, in `current_user`, replace the two lines

```python
        if google:
            return users.get(uid) if uid else None
```

with:

```python
        if google:
            return users.for_session(uid, session.get("epoch")) if uid else None
```

In `auth_callback`, add one line after `session["uid"] = user["id"]`:

```python
            session["epoch"] = users.session_epoch(user["id"])
```

Replace `auth_logout` with:

```python
        @app.post("/auth/logout")
        def auth_logout():
            # Ends every session of the account, not only this browser's.
            if g.user is not None:
                users.end_sessions(g.user["id"])
            session.clear()
            return jsonify(ok=True)
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add fc/db.py fc/users.py fc/webapp.py tests/test_db.py tests/test_users.py tests/test_signin.py
git commit -m "Make signing out end every session of the account

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Small hardening before going public

**Files:**
- Modify: `fc/users.py`, `fc/webapp.py`, `fc/auth.py`, `fc/db.py`, `tests/test_users.py`, `tests/test_signin.py`, `tests/test_auth.py`, `tests/test_db.py`

Four deferred findings from the sign-in review, each small.

**Interfaces:**
- Consumes and produces: no signatures change.

- [ ] **Step 1: Write the failing tests**

Add to `TestGoogleAccounts` in `tests/test_users.py`, and add `import threading` to the file's imports:

```python
    def test_simultaneous_first_sign_ins_make_one_account(self):
        results, errors = [], []

        def sign_in():
            try:
                results.append(self.google("g-new")["id"])
            except Exception as e:                       # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=sign_in) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(results)), 1)
```

Add to `TestSignIn` in `tests/test_signin.py`:

```python
    def test_abandoned_attempts_do_not_pile_up_in_the_cookie(self):
        client = self.app.test_client()
        with client.session_transaction() as s:
            for i in range(10):
                s[f"_state_google_{i}"] = {"data": "x"}
        self.google.profile = BRETT
        client.get("/auth/login")
        with client.session_transaction() as s:
            self.assertEqual([k for k in s if k.startswith("_state_google_")], [])
```

Add to `TestPersistentKey` in `tests/test_auth.py`, and add `import os` to the file's imports:

```python
    def test_losing_a_start_up_race_adopts_the_winners_key(self):
        self.dir.mkdir(parents=True)
        real_link = os.link

        def another_process_wins(src, dst):
            Path(dst).write_text("the-winners-key")
            raise FileExistsError(dst)

        with mock.patch("fc.auth.os.link", side_effect=another_process_wins):
            self.assertEqual(persistent_key(self.dir), "the-winners-key")
        self.assertEqual(persistent_key(self.dir), "the-winners-key")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["secret_key"])
        self.assertIs(os.link, real_link)

    def test_the_data_directory_is_created_private(self):
        persistent_key(self.dir)
        self.assertEqual(stat.S_IMODE(self.dir.stat().st_mode), 0o700)
```

Add to `TestFresh` in `tests/test_db.py`, and add `import stat` to the file's imports:

```python
    def test_the_database_and_a_new_data_directory_are_private(self):
        path = self.path.parent / "new" / "flights.db"
        db.init(path)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_an_existing_database_is_made_private_on_start(self):
        db.init(self.path)
        self.path.chmod(0o644)
        db.init(self.path)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_users tests.test_signin tests.test_auth tests.test_db 2>&1 | grep -E "^(ERROR|FAIL)|^Ran|^FAILED"`
Expected: the six new tests fail or error. The threading test may pass on some runs, because the race it guards against is rare; the others fail every time.

- [ ] **Step 3: Conflict-safe first sign-in**

In `fc/users.py`, replace the body of `upsert_google` from the `with closing(...)` line to the end with:

```python
        with closing(connect(self.path)) as db, db:
            # One statement, so two first sign-ins at once cannot both insert.
            db.execute(
                "INSERT INTO users (google_sub, email, name, picture_url,"
                " created_at) VALUES (?,?,?,?,?)"
                " ON CONFLICT(google_sub) DO UPDATE SET email = excluded.email,"
                " name = excluded.name, picture_url = excluded.picture_url",
                (sub, email, name, picture_url, datetime.now(UTC).isoformat()))
            uid = db.execute("SELECT id FROM users WHERE google_sub = ?",
                             (sub,)).fetchone()["id"]
        return self.get(uid)
```

- [ ] **Step 4: Clear stale sign-in attempts**

In `fc/webapp.py`, in `auth_login`, add before the `session["next"] = ...` line:

```python
            # Each attempt leaves a state entry in the cookie. Clear the old
            # ones, or enough abandoned attempts would outgrow the cookie.
            for key in [k for k in session if k.startswith("_state_")]:
                session.pop(key)
```

- [ ] **Step 5: Race-safe session key**

In `fc/auth.py`, replace `persistent_key` with:

```python
def persistent_key(data_dir: Path) -> str:
    """The key that signs session cookies, kept in the data directory so
    sign-ins survive a restart. Created on first use, owner-readable only.

    The key is written to a temporary file and then linked into place. A link
    either publishes the whole file or fails because another process got
    there first, so no process ever reads a half-written key and all of them
    end up using the same one."""
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = data_dir / "secret_key"
    for _ in range(3):
        try:
            key = path.read_text().strip()
        except FileNotFoundError:
            key = None
        if key:
            return key
        if key == "":
            path.unlink(missing_ok=True)       # an empty file is no key
        fresh = secrets.token_hex(32)
        tmp = data_dir / f".secret_key.{os.getpid()}.{secrets.token_hex(4)}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(fresh)
        try:
            os.link(tmp, path)
            return fresh
        except FileExistsError:
            continue                           # someone else won; read theirs
        finally:
            tmp.unlink()
    raise RuntimeError(f"could not establish a session key in {data_dir}")
```

- [ ] **Step 6: Private data directory and database file**

In `fc/db.py`, add `import os` to the imports, add this helper above `init`:

```python
def _make_private(path: Path) -> None:
    """The database holds email addresses: owner-readable only."""
    if path.exists() and (path.stat().st_mode & 0o777) != 0o600:
        os.chmod(path, 0o600)
```

and in `init` change the first statement to

```python
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
```

change the early return to

```python
        if version >= SCHEMA_VERSION:
            _make_private(path)
            return
```

and add `_make_private(path)` as the last line of `init`, after the `try` block.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: `OK`. Run it three times; the threading test must pass every time.

- [ ] **Step 8: Commit**

```bash
git add fc/users.py fc/webapp.py fc/auth.py fc/db.py tests/test_users.py tests/test_signin.py tests/test_auth.py tests/test_db.py
git commit -m "Harden first sign-in, the session key, and file permissions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The container and the Render service

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `render.yaml`

**Interfaces:**
- Consumes: `fc.wsgi:app`, `GET /healthz`.
- Produces: a container that serves the app on `$PORT`; a Render Blueprint describing one web service with a 1 GB disk at `/data`.

- [ ] **Step 1: Write the Dockerfile**

Create `Dockerfile`:

```dockerfile
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WINGMATES_AUTH=google \
    WINGMATES_DATA_DIR=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fc ./fc
COPY web ./web
COPY data ./data

# One worker process, several threads: SQLite on a local disk cannot have two
# server processes writing. The host sets PORT; 10000 is Render's default.
CMD ["sh", "-c", "exec gunicorn --workers 1 --threads 8 --timeout 60 --bind 0.0.0.0:${PORT:-10000} fc.wsgi:app"]
```

There is deliberately no access log: the sign-in callback's address carries a one-time code from Google, and it should not be written to a log.

`data/` here is the airport table in the repository, copied to `/app/data`. The persistent disk is a different place, `/data`.

Create `.dockerignore`:

```
.git
.venv
.devdata
.superpowers
.claude
.impeccable
__pycache__
*.pyc
tests
docs
README.md
```

- [ ] **Step 2: Write the Render Blueprint**

Create `render.yaml`:

```yaml
# Render Blueprint: one web service with a persistent disk.
# https://render.com/docs/blueprint-spec
services:
  - type: web
    name: wingmates
    runtime: docker
    dockerfilePath: ./Dockerfile
    dockerContext: .
    branch: main
    autoDeployTrigger: commit
    healthCheckPath: /healthz
    disk:
      name: wingmates-data
      mountPath: /data
      sizeGB: 1
    envVars:
      - key: WINGMATES_AUTH
        value: google
      - key: WINGMATES_DATA_DIR
        value: /data
      # Signs session cookies. Generated once by Render and kept across deploys.
      - key: SECRET_KEY
        generateValue: true
      # Entered in the Render dashboard; never stored in this file.
      - key: GOOGLE_CLIENT_ID
        sync: false
      - key: GOOGLE_CLIENT_SECRET
        sync: false
```

No `plan` is given: Render's default for a new web service is its smallest paid instance, which is the one wanted. A service with a disk must be on a paid instance, and cannot run more than one instance.

- [ ] **Step 3: Run the exact server command locally**

This is the first time `fc/wsgi.py` and gunicorn run together.

```bash
D=$(mktemp -d)
WINGMATES_AUTH=google WINGMATES_DATA_DIR=$D GOOGLE_CLIENT_ID=x GOOGLE_CLIENT_SECRET=y \
  SECRET_KEY=k WINGMATES_BASE_URL=http://localhost:10000 PORT=10000 \
  sh -c 'exec .venv/bin/gunicorn --workers 1 --threads 8 --timeout 60 --bind 127.0.0.1:${PORT:-10000} fc.wsgi:app' &
sleep 2
curl -s http://localhost:10000/healthz; echo
curl -s -H "Host: 10.214.3.7:10000" http://localhost:10000/healthz; echo
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://localhost:10000/
curl -s http://localhost:10000/api/me; echo
ls -l $D
kill %1
```

Expected, in order: `{"ok":true}`, `{"ok":true}`, `302 http://localhost:10000/login`, `{"error":"sign in required"}`, and a listing showing `flights.db` with mode `-rw-------`.

Then confirm it refuses to start without sign-in:

```bash
WINGMATES_AUTH=local WINGMATES_DATA_DIR=$(mktemp -d) .venv/bin/python -c "import fc.wsgi" 2>&1 | tail -1
```

Expected: a `RuntimeError` line containing `WINGMATES_AUTH=google`.

- [ ] **Step 4: Build and run the container, if Docker is running**

Run: `docker info --format '{{.ServerVersion}}'`

If that prints a version, build and run the real image:

```bash
docker build -t wingmates-local .
docker run -d --rm --name wingmates-check -p 10001:10000 \
  -e GOOGLE_CLIENT_ID=x -e GOOGLE_CLIENT_SECRET=y -e SECRET_KEY=k \
  -e WINGMATES_BASE_URL=http://localhost:10001 wingmates-local
sleep 3
curl -s http://localhost:10001/healthz; echo
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://localhost:10001/
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:10001/static/style.css
curl -s "http://localhost:10001/login" | grep -c "Continue with Google"
docker stop wingmates-check
```

Expected: `{"ok":true}`, `302 http://localhost:10001/login`, `200`, `1`.

If Docker is not running, say so in the final report: the image will then be built for the first time on Render, and Step 3 is the only local evidence.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore render.yaml
git commit -m "Add the container and the Render service definition

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Deploy guide and README

**Files:**
- Create: `docs/deploy-render.md`
- Modify: `README.md`, `docs/google-sign-in-setup.md`

- [ ] **Step 1: Write the deploy guide**

Create `docs/deploy-render.md`:

```markdown
# Deploying Wingmates on Render

Wingmates runs as one small web service with a 1 GB disk. Render's free
instances sleep and cannot have a disk, so this uses the smallest paid
instance: about $7 a month, plus $0.25 a month for the disk.

## Before you start

- Google sign-in is set up: see [google-sign-in-setup.md](google-sign-in-setup.md).
- The code is pushed to the `main` branch on GitHub.

## 1. Create the service

1. Sign up at https://render.com and add a payment method.
2. In the dashboard choose **New**, then **Blueprint**.
3. Connect your GitHub account and give Render access to the `wingmates`
   repository.
4. Render reads `render.yaml` and shows one web service, `wingmates`, with a
   disk. Check the instance type is the smallest paid one.
5. It asks for two values. Open `~/.wingmates/google-client.json` and copy:
   - `GOOGLE_CLIENT_ID`: the `client_id` value
   - `GOOGLE_CLIENT_SECRET`: the `client_secret` value
6. Apply. The first build takes a few minutes.

## 2. Tell Google the new address

Render shows the service's address, like `https://wingmates-ab12.onrender.com`.

1. In the Google Cloud console open **Google Auth Platform**, then **Clients**,
   then your client.
2. Under **Authorized redirect URIs** add, with no trailing slash:
   `https://YOUR-ADDRESS/auth/callback`
3. Save. Keep the `http://localhost:8817/auth/callback` entry for local use.

## 3. Sign in and invite people

1. Open the address and press **Continue with Google**.
2. Choose your username.
3. To bring flights across from your own machine, use **Export** there and
   **Import CSV** here.
4. Add each friend's Google address under **Audience**, **Test users** in the
   Google console, then send them the address.

## Updating

Every push to `main` deploys automatically. Because the service has a disk,
Render stops the old version before starting the new one, so the site is
unavailable for a few seconds during a deploy.

## Backups

Render snapshots the disk once a day and keeps each snapshot for at least
seven days. To restore, open the service's **Disks** page and pick a snapshot;
everything written after it is lost. Each person can also export their own
flights as CSV at any time.

## Settings

| Variable | Set by | Purpose |
|---|---|---|
| `WINGMATES_AUTH` | `render.yaml` | `google`. The server refuses to start otherwise. |
| `WINGMATES_DATA_DIR` | `render.yaml` | `/data`, the disk. |
| `SECRET_KEY` | Render, generated once | Signs session cookies. Changing it signs everyone out. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | you, in the dashboard | The Google client. |
| `WINGMATES_BASE_URL` | optional | Set this when you add a custom domain. Otherwise the service's `onrender.com` address is used. |

## A custom domain

Add the domain in the service's **Settings**, set `WINGMATES_BASE_URL` to
`https://your-domain`, and add `https://your-domain/auth/callback` to the
Google client's redirect URIs.

## If something is wrong

- **The deploy never goes live.** Open **Logs**. A line saying a hosted
  Wingmates needs `WINGMATES_AUTH=google` means that variable was removed. A
  line about Google sign-in needing a client means one of the two Google
  values is empty.
- **Google shows `redirect_uri_mismatch`.** The redirect URI in the Google
  console does not exactly match `https://YOUR-ADDRESS/auth/callback`.
- **Google shows `access_denied`.** That person is not in the test users list.
- **Everyone was signed out.** `SECRET_KEY` changed, or you pressed Sign out:
  signing out ends every session of your account, on every device.
```

- [ ] **Step 2: Update the README**

In the opening section, after the paragraph that begins `By default there is no sign-in:`, add:

```markdown
To put it on the internet for friends, see
[docs/deploy-render.md](docs/deploy-render.md).
```

In the Layout block add:

```
fc/hosted.py, wsgi.py   the app as a hosted server runs it (gunicorn)
Dockerfile, render.yaml the container and the Render service
```

and change the `requirements.txt` line to `requirements.txt        Flask, Authlib, requests, gunicorn`.

In the API block add:

```
GET  /healthz                        health check for the host
```

In "Not built yet", replace the text with: `Importing from calendar events or email confirmations, blocking and reporting, and a custom domain.`

In `docs/google-sign-in-setup.md`, replace the sentence that begins `Add the hosted address here as well` with:

```markdown
When the app is deployed, add its address here too: see
[deploy-render.md](deploy-render.md).
```

- [ ] **Step 3: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add docs/deploy-render.md docs/google-sign-in-setup.md README.md
git commit -m "Add the Render deploy guide

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Go live

Render deploys the `main` branch from GitHub, so this task starts only after the branch has been reviewed, merged and pushed, which needs the owner's say. Every step here is done by the owner; none can be automated, because they involve the owner's Render account, payment method and Google account.

- [ ] **Step 1: Merge and push**

Ask the owner for approval, then fast-forward `main` to this branch and push.

- [ ] **Step 2: Upgrade the owner's local database**

Start the app locally once in `google` mode. Their local database is schema version 1 and upgrades to 2 on start. Confirm their account and flight are still there after signing in again. They will be asked to sign in once, because their existing cookie has no session epoch.

- [ ] **Step 3: Ask the owner to create the service**

Walk them through sections 1 and 2 of `docs/deploy-render.md`. Ask them to report the service address and whether the deploy went live. If it did not, ask for the last lines of the Render log.

- [ ] **Step 4: Check the live site from outside**

With the address they report:

```bash
A=https://THEIR-ADDRESS
curl -s $A/healthz; echo
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" $A/
curl -s $A/api/me; echo
curl -sI $A/auth/login | grep -i "^location:" | grep -c "accounts.google.com"
```

Expected: `{"ok":true}`, `302 https://THEIR-ADDRESS/login`, `{"error":"sign in required"}`, `1`.

- [ ] **Step 5: Ask the owner to confirm the real thing**

1. They can sign in on the live site and choose a username.
2. Importing their exported CSV brings their flights across.
3. A friend, added as a test user, can sign in from their own device.
4. The two can find each other by username, become mates, and see each other's wingspans and routes.
5. After pushing any small change to `main`, the site redeploys and both are still signed in with their flights intact.
