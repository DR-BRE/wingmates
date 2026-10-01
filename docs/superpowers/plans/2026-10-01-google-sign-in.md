# Google Sign-In Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real accounts: sign in with Google, choose a username on first visit, stay signed in for 30 days, sign out, and delete your account.

**Architecture:** A second auth mode, `google`, alongside the existing `local` mode. `fc/auth.py` is the only module that talks to Google, behind a two-method object (`begin`, `finish`) that tests replace with a fake, so no test touches the network. `fc/webapp.py` gains a session-based current user, the 401 and 409 rules, and the sign-in routes. Local mode keeps working exactly as it does today.

**Tech Stack:** Python 3.11+, Flask 3.1, Authlib 1.x (OpenID Connect), requests, SQLite, `unittest`, vanilla JS.

**Spec:** `docs/superpowers/specs/2026-10-01-mates-and-wingspans-design.md`

This plan is build step 2 of the spec. **Deferred to plan 3:** Dockerfile, gunicorn, `/healthz`, running behind a proxy, host setup.

## Global Constraints

- New dependencies: `Authlib>=1.3,<2` and `requests>=2.31,<3`. Nothing else.
- All tests are offline. No test may contact Google; the sign-in object is always a fake in tests.
- Run tests with `.venv/bin/python -m unittest discover -s tests -t .`
- Google scopes are exactly `openid email profile`.
- A Google account is identified by its `sub` value, never by email.
- A new Google account has `username` NULL until the person chooses one. Username rules are unchanged from plan 1 and a username can be set only once.
- In `google` mode: every `/api/` route answers 401 `{"error": "sign in required"}` when signed out, including `/api/me`. With no username yet, every `/api/` route except `/api/me`, `/api/username` and `/api/account/delete` answers 409 `{"error": "choose a username first"}`.
- In `google` mode Live defaults to off and dev users are ignored.
- In `local` mode nothing changes, and `/auth/login`, `/auth/callback`, `/auth/logout`, `/api/username` and `/api/account/delete` do not exist (404).
- The session cookie holds only the user id. It is HttpOnly, SameSite=Lax, Secure when the base URL starts with `https://`, and lasts 30 days.
- The post-sign-in return address is used only if it is a path on this site: it starts with `/`, does not start with `//`, and contains no backslash or control character. Otherwise `/`.
- Secrets (`client_secret`, `SECRET_KEY`) are never printed, logged, committed, or placed in a `repr`.
- Email is stored but never returned by any route.
- End every commit message with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

Each of these has a test in the task named.

1. **A Google profile with no name or no picture.** Expected: the account is created with a usable display name and no picture, no crash. Task 2.
2. **Opening the app at `127.0.0.1` when Google redirects back to `localhost`.** Cookies do not carry between the two names, so sign-in would fail with a state error. Expected: page requests are redirected to the configured address first. Task 4.
3. **A session cookie for an account that has since been deleted.** Expected: 401, never a 500, and never another person's account. Task 4.
4. **Two people choosing the same username at nearly the same time.** Expected: the second gets "taken", not a 500. Task 2.
5. **A crafted return address** (`//evil.example`, `/\evil.example`, a full URL, a line break). Expected: the person lands on `/`. Task 3.

## File Structure

| File | Responsibility |
|---|---|
| `requirements.txt` (modify) | Adds Authlib and requests. |
| `fc/config.py` (modify) | `google` mode; Google client id and secret from env or the downloaded client file. |
| `fc/users.py` (modify) | `upsert_google`, `set_username`. |
| `fc/auth.py` (new) | `GoogleSignIn`, `safe_next`, `persistent_key`. The only module that imports Authlib. |
| `fc/webapp.py` (modify) | Session user, 401/409 rules, canonical-host redirect, sign-in routes, username and account-delete routes, page routing. |
| `web/login.html`, `web/welcome.html` (new) | Sign-in page; choose-a-username page. |
| `web/app.js` (modify) | Redirect on 401/409; shared `avatar`; account menu. |
| `web/social.js` (modify) | Uses the shared `avatar`. |
| `web/style.css` (modify) | Gate pages, header avatar, account menu. |
| `run.py`, `.claude/launch.json` (modify) | Open the configured address in `google` mode; a launch entry for it. |
| `docs/google-sign-in-setup.md` (new), `README.md` (modify) | Setup guide and settings. |
| `tests/test_config.py`, `tests/test_users.py` (modify); `tests/test_auth.py`, `tests/test_signin.py` (new) | One per module. |

---

### Task 1: Config for Google mode

**Files:**
- Modify: `requirements.txt`, `fc/config.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Config` gains fields `google_client_id: str | None` and `google_client_secret: str | None`. `Config.from_env` accepts `WINGMATES_AUTH=google`, for which it requires a client id and secret from `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, or else from `<data_dir>/google-client.json` (the file Google's console downloads, shape `{"web": {"client_id": ..., "client_secret": ...}}`). It raises `ValueError` if neither is available. `live` defaults to `auth == "local"`; `dev_users` is `False` unless `auth == "local"`. Secret fields are excluded from `repr`.

- [ ] **Step 1: Create the branch and install the libraries**

```bash
cd ~/flighty-clone
git checkout -b google-sign-in
git add docs/superpowers && git commit -m "Add the Google sign-in plan and spec amendments

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
printf 'Flask>=3.1,<4\nAuthlib>=1.3,<2\nrequests>=2.31,<3\n' > requirements.txt
.venv/bin/python -m pip install -q -r requirements.txt
.venv/bin/python -c "import authlib, requests; print(authlib.__version__)"
```

Expected: a version starting `1.`

- [ ] **Step 2: Write the failing tests**

In `tests/test_config.py`, add `import json` and `import tempfile` to the imports, replace `test_an_auth_mode_other_than_local_is_refused` with the first test below, and add the rest to `TestConfig`:

```python
    def test_an_unknown_auth_mode_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            Config.from_env({"WINGMATES_AUTH": "ldap"})
        self.assertIn("WINGMATES_AUTH", str(cm.exception))

    def google_env(self, **extra):
        return {"WINGMATES_AUTH": "google", "GOOGLE_CLIENT_ID": "id-1",
                "GOOGLE_CLIENT_SECRET": "shh", **extra}

    def test_google_mode_reads_the_client_from_the_environment(self):
        c = Config.from_env(self.google_env())
        self.assertEqual((c.auth, c.google_client_id, c.google_client_secret),
                         ("google", "id-1", "shh"))

    def test_google_mode_turns_live_off_and_ignores_dev_users(self):
        c = Config.from_env(self.google_env(WINGMATES_DEV_USERS="1"))
        self.assertEqual((c.live, c.dev_users), (False, False))
        self.assertTrue(Config.from_env(self.google_env(WINGMATES_LIVE="1")).live)

    def test_google_mode_falls_back_to_the_downloaded_client_file(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "google-client.json").write_text(json.dumps(
                {"web": {"client_id": "file-id", "client_secret": "file-shh"}}))
            c = Config.from_env({"WINGMATES_AUTH": "google",
                                 "WINGMATES_DATA_DIR": d})
        self.assertEqual((c.google_client_id, c.google_client_secret),
                         ("file-id", "file-shh"))

    def test_google_mode_without_a_client_refuses_to_start(self):
        with tempfile.TemporaryDirectory() as d:
            for content in (None, "not json", '{"installed": {}}', '[]'):
                if content is not None:
                    (Path(d) / "google-client.json").write_text(content)
                with self.assertRaises(ValueError) as cm:
                    Config.from_env({"WINGMATES_AUTH": "google",
                                     "WINGMATES_DATA_DIR": d})
                self.assertIn("GOOGLE_CLIENT_ID", str(cm.exception))
                self.assertIn("google-client.json", str(cm.exception))

    def test_secrets_are_not_in_the_repr(self):
        text = repr(Config.from_env(self.google_env(SECRET_KEY="key-material")))
        self.assertNotIn("shh", text)
        self.assertNotIn("key-material", text)
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_config -v`
Expected: the new tests fail with `ValueError: WINGMATES_AUTH must be 'local'` or `AttributeError`.

- [ ] **Step 4: Implement**

Replace `fc/config.py` with:

```python
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
            base_url=(env.get("WINGMATES_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            secret_key=env.get("SECRET_KEY") or None,
            google_client_id=cid,
            google_client_secret=secret,
        )
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt fc/config.py tests/test_config.py
git commit -m "Add google auth mode to Config

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Google accounts and choosing a username

**Files:**
- Modify: `fc/users.py`, `tests/test_users.py`

**Interfaces:**
- Consumes: `fc.db.connect`; `validate_username`.
- Produces, on `Users`:
  - `upsert_google(sub: str, email: str | None, name: str | None, picture_url: str | None) -> dict` — creates the account with `username` NULL on first sight of `sub`; otherwise refreshes email, name and picture. Returns the public user dict.
  - `set_username(user_id: int, raw: str) -> dict` — sets the username if the user has none. Raises `ValueError` if it is malformed, reserved, taken, or the user already has one.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_users.py`, above the `if __name__` line:

```python
class TestGoogleAccounts(UsersCase):

    def google(self, sub="g-1", email="brett@example.com", name="Brett F",
               picture_url="https://img.example/b.png"):
        return self.users.upsert_google(sub, email, name, picture_url)

    def test_first_sign_in_creates_an_account_without_a_username(self):
        u = self.google()
        self.assertEqual(set(u), {"id", "username", "name", "picture_url"})
        self.assertEqual((u["username"], u["name"], u["picture_url"]),
                         (None, "Brett F", "https://img.example/b.png"))

    def test_later_sign_ins_refresh_the_profile_and_keep_the_account(self):
        first = self.google()
        self.users.set_username(first["id"], "brett")
        again = self.google(email="new@example.com", name="Brett Francoeur",
                            picture_url=None)
        self.assertEqual((again["id"], again["username"], again["name"],
                          again["picture_url"]),
                         (first["id"], "brett", "Brett Francoeur", None))

    def test_a_different_sub_is_a_different_account_even_with_the_same_email(self):
        self.assertNotEqual(self.google("g-1")["id"], self.google("g-2")["id"])

    def test_a_profile_without_a_name_gets_a_usable_one(self):
        self.assertEqual(self.google(name=None)["name"], "brett")
        self.assertEqual(self.google("g-2", email=None, name="  ")["name"],
                         "Wingmate")

    def test_an_account_without_a_username_cannot_be_looked_up(self):
        self.google()
        self.assertIsNone(self.users.by_username(""))
        self.assertIsNone(self.users.by_username("None"))


class TestSetUsername(UsersCase):

    def setUp(self):
        super().setUp()
        self.uid = self.users.upsert_google("g-1", "a@example.com", "A", None)["id"]

    def test_it_is_normalised_and_stored(self):
        self.assertEqual(self.users.set_username(self.uid, " @Brett ")["username"],
                         "brett")
        self.assertEqual(self.users.by_username("brett")["id"], self.uid)

    def test_it_can_only_be_set_once(self):
        self.users.set_username(self.uid, "brett")
        with self.assertRaises(ValueError) as cm:
            self.users.set_username(self.uid, "other")
        self.assertIn("already", str(cm.exception))
        self.assertEqual(self.users.get(self.uid)["username"], "brett")

    def test_malformed_reserved_and_taken_names_are_refused(self):
        self.users.create("Ann", "ann")
        for bad, word in (("ab", "3 to 20"), ("admin", "reserved"),
                          ("ANN", "taken")):
            with self.assertRaises(ValueError) as cm:
                self.users.set_username(self.uid, bad)
            self.assertIn(word, str(cm.exception))
        self.assertIsNone(self.users.get(self.uid)["username"])

    def test_the_second_of_two_people_choosing_a_name_is_told_it_is_taken(self):
        other = self.users.upsert_google("g-2", "b@example.com", "B", None)["id"]
        self.users.set_username(other, "brett")
        with self.assertRaises(ValueError) as cm:
            self.users.set_username(self.uid, "brett")
        self.assertIn("taken", str(cm.exception))

    def test_a_missing_user_is_refused(self):
        with self.assertRaises(ValueError):
            self.users.set_username(999, "brett")
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_users -v`
Expected: errors with `AttributeError: 'Users' object has no attribute 'upsert_google'`

- [ ] **Step 3: Implement**

In `fc/users.py`, add these two methods to `Users`, after `create`:

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_users -v`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add fc/users.py tests/test_users.py
git commit -m "Add Google accounts and one-time username choice to the user store

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The sign-in module

**Files:**
- Create: `fc/auth.py`, `tests/test_auth.py`

**Interfaces:**
- Consumes: Authlib's Flask client.
- Produces:
  - `fc.auth.safe_next(value) -> str` — `value` if it is a path on this site, else `"/"`.
  - `fc.auth.persistent_key(data_dir: Path) -> str` — a random session-signing key stored in `<data_dir>/secret_key` with mode 600; created on first call, returned unchanged afterwards.
  - `class GoogleSignIn(app: Flask, client_id: str, client_secret: str)` with `begin(redirect_uri: str) -> Response` (redirect to Google) and `finish() -> dict | None` (the profile `{"sub", "email", "name", "picture_url"}`, or `None` if the person cancelled or the response did not verify).

`GoogleSignIn` has no unit test: exercising it means contacting Google. It is covered by the manual check in Task 6. Everything else here is tested.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auth.py`:

```python
"""Sign-in helper tests. Offline: nothing here contacts Google."""
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.auth import persistent_key, safe_next


class TestSafeNext(unittest.TestCase):

    def test_a_path_on_this_site_is_kept(self):
        for ok in ("/", "/welcome", "/?tab=social", "/a/b?c=d#e"):
            self.assertEqual(safe_next(ok), ok)

    def test_anything_that_could_leave_the_site_becomes_the_home_page(self):
        for bad in ("https://evil.example", "//evil.example", "/\\evil.example",
                    "evil", "", None, 5, "/ok\nSet-Cookie: x", "/\tx",
                    "javascript:alert(1)"):
            self.assertEqual(safe_next(bad), "/", repr(bad))


class TestPersistentKey(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "data"

    def test_it_is_created_once_and_then_reused(self):
        first = persistent_key(self.dir)
        self.assertEqual(len(first), 64)
        self.assertEqual(persistent_key(self.dir), first)

    def test_the_file_is_readable_only_by_its_owner(self):
        persistent_key(self.dir)
        mode = stat.S_IMODE((self.dir / "secret_key").stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_an_empty_key_file_is_replaced(self):
        self.dir.mkdir(parents=True)
        (self.dir / "secret_key").write_text("")
        self.assertEqual(len(persistent_key(self.dir)), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_auth -v`
Expected: `ModuleNotFoundError: No module named 'fc.auth'`

- [ ] **Step 3: Implement**

Create `fc/auth.py`:

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_auth -v`
Expected: 5 tests, `OK`.

Also confirm the Authlib names used above exist in the installed version:

Run: `.venv/bin/python -c "from fc.auth import GoogleSignIn; from flask import Flask; GoogleSignIn(Flask('x'), 'id', 'secret'); print('constructs')"`
Expected: `constructs` (registering a client does not contact Google).

- [ ] **Step 5: Commit**

```bash
git add fc/auth.py tests/test_auth.py
git commit -m "Add the Google sign-in module

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Sessions, the 401 and 409 rules, and the sign-in routes

**Files:**
- Create: `web/login.html`, `web/welcome.html`, `tests/test_signin.py`
- Modify: `fc/webapp.py`, `web/style.css`

**Interfaces:**
- Consumes: `Config.auth`, `.google_client_id`, `.google_client_secret`, `.data_dir`, `.base_url`; `GoogleSignIn`, `safe_next`, `persistent_key`; `Users.upsert_google`, `.set_username`, `.delete`, `.get`.
- Produces: `create_app(config, tracker=None, airports=None, sign_in=None)`. `sign_in` is any object with `begin(redirect_uri)` and `finish()`; when omitted in `google` mode a `GoogleSignIn` is built. New routes, `google` mode only:

```
GET  /login                       sign-in page (redirects to / if signed in)
GET  /welcome                     choose-a-username page
GET  /auth/login?next=            start sign-in
GET  /auth/callback               finish sign-in, set the session
POST /auth/logout                 clear the session → {"ok": true}
POST /api/username {username}     choose a username → the user
POST /api/account/delete {confirm: "DELETE"} → {"ok": true}
```

`GET /` redirects to `/login` when signed out and to `/welcome` when the account has no username.

- [ ] **Step 1: Write the two pages**

They must exist before the page tests can pass. Create `web/login.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in — Wingmates</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body class="gate">
<main class="gatebox">
  <div class="brand"><span class="glyph">✈</span> WING<span class="dim">MATES</span></div>
  <h1>Your flights on a globe, with your mates.</h1>
  <a class="gatebtn" href="/auth/login">Continue with Google</a>
  <p class="hint error" id="err" hidden>Sign-in didn't finish. Please try again.</p>
  <p class="hint">Wingmates uses your Google name and picture. It never sees
     your password and never reads your email.</p>
</main>
<script>
if (new URLSearchParams(location.search).has('error')) {
  document.getElementById('err').hidden = false;
}
</script>
</body>
</html>
```

Create `web/welcome.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Choose a username — Wingmates</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body class="gate">
<main class="gatebox">
  <div class="brand"><span class="glyph">✈</span> WING<span class="dim">MATES</span></div>
  <h1>Choose your username</h1>
  <form id="name-form" autocomplete="off">
    <div class="row">
      <input id="username" placeholder="username" spellcheck="false"
             autocapitalize="none" autofocus required minlength="3"
             maxlength="21" aria-label="Username">
      <button type="submit" id="name-btn">Continue</button>
    </div>
    <p class="hint" id="name-hint">3 to 20 characters: letters, digits and
       underscore. This is how mates find you, and it can't be changed later.</p>
  </form>
  <button class="quiet" id="out">Sign out</button>
</main>
<script>
const send = (path, body) => fetch(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}) });

document.getElementById('name-form').addEventListener('submit', async e => {
  e.preventDefault();
  const hint = document.getElementById('name-hint');
  const res = await send('/api/username',
                         { username: document.getElementById('username').value });
  if (res.ok) { location.href = '/'; return; }
  if (res.status === 401) { location.href = '/login'; return; }
  const data = await res.json().catch(() => ({ error: 'Something went wrong.' }));
  hint.className = 'hint error';
  hint.textContent = data.error;
});

document.getElementById('out').addEventListener('click', async () => {
  await send('/auth/logout');
  location.href = '/login';
});
</script>
</body>
</html>
```

The input allows 21 characters so a pasted `@name` of full length still fits; the server enforces the real rule.

Append to `web/style.css`:

```css
body.gate{display:flex;align-items:center;justify-content:center;overflow:auto;
  background:radial-gradient(ellipse at 50% 35%,#0c1622 0%,#06090d 70%)}
.gatebox{display:block;height:auto;width:min(420px,calc(100vw - 32px));padding:32px 28px;
  background:var(--panel);border:1px solid var(--line);border-radius:6px}
.gatebox h1{font-size:19px;font-weight:600;margin:22px 0 20px;line-height:1.35}
.gatebox .hint{margin:14px 0 0}
.gatebtn{display:block;text-align:center;text-decoration:none;padding:12px 14px;
  border-radius:3px;background:var(--accent-dim);border:1px solid #17414a;color:var(--accent);
  font-family:var(--mono);font-size:12px;letter-spacing:.09em;text-transform:uppercase}
.gatebtn:hover{background:#15434c}
.gatebox #out{margin-top:22px}
```

`.gatebox` is a `<main>`, and the app's `main{display:flex;height:calc(100vh - 52px)}` rule would stretch it, so the rule above resets `display` and `height`.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_signin.py`:

```python
"""Sign-in tests, through Flask's test client, with a fake in place of Google.
Offline."""
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import redirect

from fc.config import Config
from fc.webapp import create_app
from tests.helpers import stores

BASE = "http://localhost"
ORIGIN = {"Origin": BASE}
BRETT = {"sub": "g-1", "email": "brett@example.com", "name": "Brett F",
         "picture_url": "https://img.example/b.png"}
ANN = {"sub": "g-2", "email": "ann@example.com", "name": "Ann", "picture_url": None}


class FakeSignIn:
    """Stands in for Google: begin() goes straight to the callback, and
    finish() returns whatever profile the test set."""
    def __init__(self):
        self.profile = None
        self.redirect_uri = None

    def begin(self, redirect_uri):
        self.redirect_uri = redirect_uri
        return redirect("/auth/callback")

    def finish(self):
        return self.profile


class SignInCase(unittest.TestCase):
    def setUp(self):
        self.dir, self.airports, self.history, self.users = stores(self)
        self.google = FakeSignIn()
        self.app = create_app(
            Config(auth="google", live=False, data_dir=self.dir, base_url=BASE,
                   google_client_id="id", google_client_secret="secret"),
            airports=self.airports, sign_in=self.google)
        self.client = self.app.test_client()

    def post(self, path, body=None, client=None):
        return (client or self.client).post(path, json=body or {}, headers=ORIGIN)

    def sign_in(self, profile=BRETT, username=None, next=None):
        """A new browser, signed in as `profile`. Returns (client, the
        response to the callback)."""
        client = self.app.test_client()
        self.google.profile = profile
        start = client.get("/auth/login" + (f"?next={quote(next)}" if next else ""))
        done = client.get(start.headers["Location"])
        if username:
            self.assertEqual(self.post("/api/username", {"username": username},
                                       client).status_code, 200)
        return client, done


class TestSignedOut(SignInCase):

    def test_every_api_route_answers_401(self):
        checked = 0
        for rule in self.app.url_map.iter_rules():
            if not rule.rule.startswith("/api/"):
                continue
            path = re.sub(r"<[^>]+>", "1", rule.rule)
            for method in rule.methods & {"GET", "POST"}:
                r = (self.client.get(path) if method == "GET"
                     else self.post(path))
                self.assertEqual((r.status_code, r.get_json()),
                                 (401, {"error": "sign in required"}),
                                 f"{method} {path}")
                checked += 1
        self.assertGreaterEqual(checked, 18)

    def test_pages_send_you_to_the_sign_in_page(self):
        self.assertEqual(self.client.get("/").headers["Location"], "/login")
        self.assertEqual(self.client.get("/welcome").headers["Location"], "/login")
        with self.client.get("/login") as r:
            self.assertEqual(r.status_code, 200)
            self.assertIn(b"Continue with Google", r.data)

    def test_static_files_need_no_sign_in(self):
        with self.client.get("/static/style.css") as r:
            self.assertEqual(r.status_code, 200)


class TestSignIn(SignInCase):

    def test_google_is_asked_to_return_to_the_configured_address(self):
        self.sign_in()
        self.assertEqual(self.google.redirect_uri, BASE + "/auth/callback")

    def test_a_new_account_must_choose_a_username_before_anything_else(self):
        client, done = self.sign_in()
        self.assertEqual(done.headers["Location"], "/")
        self.assertEqual(client.get("/").headers["Location"], "/welcome")
        me = client.get("/api/me").get_json()
        self.assertEqual((me["username"], me["name"], me["auth"]),
                         (None, "Brett F", "google"))
        self.assertNotIn("email", me)
        for path in ("/api/history", "/api/social", "/api/airports?q=atl"):
            r = client.get(path)
            self.assertEqual((r.status_code, r.get_json()),
                             (409, {"error": "choose a username first"}), path)
        with client.get("/welcome") as r:
            self.assertEqual(r.status_code, 200)

    def test_choosing_a_username_opens_the_app(self):
        client, _ = self.sign_in()
        r = self.post("/api/username", {"username": "@Brett"}, client)
        self.assertEqual((r.status_code, r.get_json()["username"]), (200, "brett"))
        with client.get("/") as page:
            self.assertEqual(page.status_code, 200)
        self.assertEqual(client.get("/api/history").status_code, 200)
        self.assertEqual(client.get("/welcome").headers["Location"], "/")
        self.assertEqual(client.get("/login").headers["Location"], "/")

    def test_username_problems_are_explained(self):
        self.sign_in(ANN, username="ann")
        client, _ = self.sign_in()
        for bad, word in (("ab", "3 to 20"), ("admin", "reserved"),
                          ("Ann", "taken"), (None, "3 to 20"), (["x"], "3 to 20")):
            r = self.post("/api/username", {"username": bad}, client)
            self.assertEqual(r.status_code, 400, repr(bad))
            self.assertIn(word, r.get_json()["error"])
        self.post("/api/username", {"username": "brett"}, client)
        r = self.post("/api/username", {"username": "other"}, client)
        self.assertEqual(r.status_code, 400)
        self.assertIn("already", r.get_json()["error"])

    def test_signing_in_again_reuses_the_account(self):
        first, _ = self.sign_in(username="brett")
        uid = first.get("/api/me").get_json()["id"]
        again, _ = self.sign_in({**BRETT, "email": "moved@example.com",
                                 "name": "Brett Francoeur"})
        me = again.get("/api/me").get_json()
        self.assertEqual((me["id"], me["username"], me["name"]),
                         (uid, "brett", "Brett Francoeur"))

    def test_a_cancelled_sign_in_returns_to_the_sign_in_page(self):
        client, done = self.sign_in(profile=None)
        self.assertEqual(done.headers["Location"], "/login?error=1")
        self.assertEqual(client.get("/api/me").status_code, 401)

    def test_the_return_address_is_used_only_if_it_is_on_this_site(self):
        _, done = self.sign_in(next="/?tab=social")
        self.assertEqual(done.headers["Location"], "/?tab=social")
        for bad in ("https://evil.example", "//evil.example", "/\\evil.example"):
            _, done = self.sign_in(next=bad)
            self.assertEqual(done.headers["Location"], "/", bad)


class TestSessions(SignInCase):

    def test_the_cookie_is_httponly_lax_and_lasts_thirty_days(self):
        self.google.profile = BRETT
        client = self.app.test_client()
        done = client.get(client.get("/auth/login").headers["Location"])
        cookie = done.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Expires=", cookie)
        self.assertNotIn("Secure", cookie)        # the base URL here is http

    def test_sign_out_ends_the_session(self):
        client, _ = self.sign_in(username="brett")
        self.assertEqual(self.post("/auth/logout", client=client).get_json(),
                         {"ok": True})
        self.assertEqual(client.get("/api/me").status_code, 401)
        self.assertEqual(client.get("/auth/logout").status_code, 405)

    def test_a_session_for_a_deleted_account_is_signed_out(self):
        client, _ = self.sign_in(username="brett")
        uid = client.get("/api/me").get_json()["id"]
        self.users.delete(uid)
        ann, _ = self.sign_in(ANN, username="ann")
        r = client.get("/api/me")
        self.assertEqual((r.status_code, r.get_json()),
                         (401, {"error": "sign in required"}))
        self.assertEqual(ann.get("/api/me").get_json()["username"], "ann")

    def test_page_requests_on_another_local_name_move_to_the_configured_one(self):
        r = self.client.get("/?tab=social", base_url="http://127.0.0.1")
        self.assertEqual((r.status_code, r.headers["Location"]),
                         (302, BASE + "/?tab=social"))
        r = self.client.get("/auth/login", base_url="http://127.0.0.1")
        self.assertEqual(r.headers["Location"], BASE + "/auth/login")
        # API calls are answered, not redirected.
        self.assertEqual(self.client.get("/api/me",
                                         base_url="http://127.0.0.1").status_code, 401)


class TestAccountDelete(SignInCase):

    def test_it_needs_the_word_delete(self):
        client, _ = self.sign_in(username="brett")
        for confirm in (None, "delete", "yes", True):
            r = self.post("/api/account/delete", {"confirm": confirm}, client)
            self.assertEqual(r.status_code, 400, repr(confirm))
        self.assertEqual(client.get("/api/me").status_code, 200)

    def test_it_removes_the_account_its_flights_and_frees_the_username(self):
        client, _ = self.sign_in(username="brett")
        uid = client.get("/api/me").get_json()["id"]
        self.post("/api/history", {"date": "2024-03-09", "from": "ATL",
                                   "to": "LHR"}, client)
        self.assertEqual(self.post("/api/account/delete", {"confirm": "DELETE"},
                                   client).get_json(), {"ok": True})
        self.assertEqual(client.get("/api/me").status_code, 401)
        self.assertIsNone(self.users.get(uid))
        self.assertEqual(self.history.for_user(uid).list(), [])
        again, _ = self.sign_in(username="brett")
        self.assertNotEqual(again.get("/api/me").get_json()["id"], uid)

    def test_an_account_with_no_username_can_still_be_deleted(self):
        client, _ = self.sign_in()
        self.assertEqual(self.post("/api/account/delete", {"confirm": "DELETE"},
                                   client).status_code, 200)


class TestTwoPeople(SignInCase):

    def test_two_signed_in_people_can_become_mates(self):
        brett, _ = self.sign_in(username="brett")
        ann, _ = self.sign_in(ANN, username="ann")
        self.post("/api/history", {"date": "2024-03-09", "from": "ATL",
                                   "to": "LHR"}, ann)
        self.post("/api/mates/request", {"username": "ann"}, brett)
        brett_id = brett.get("/api/me").get_json()["id"]
        self.post(f"/api/mates/{brett_id}/accept", client=ann)
        mate = brett.get("/api/social").get_json()["mates"][0]
        self.assertEqual((mate["username"], mate["name"]), ("ann", "Ann"))
        self.assertNotIn("email", mate)


class TestLocalModeIsUnchanged(unittest.TestCase):

    def setUp(self):
        self.dir, self.airports, _, _ = stores(self)
        self.client = create_app(Config(data_dir=self.dir, live=False),
                                 airports=self.airports).test_client()

    def test_sign_in_routes_do_not_exist(self):
        self.assertEqual(self.client.get("/auth/login").status_code, 404)
        self.assertEqual(self.client.get("/auth/callback").status_code, 404)
        for path in ("/auth/logout", "/api/username", "/api/account/delete"):
            r = self.client.post(path, json={}, headers=ORIGIN)
            self.assertEqual(r.status_code, 404, path)

    def test_gate_pages_lead_back_to_the_app(self):
        self.assertEqual(self.client.get("/login").headers["Location"], "/")
        self.assertEqual(self.client.get("/welcome").headers["Location"], "/")
        self.assertEqual(self.client.get("/api/me").get_json()["username"], "you")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_signin 2>&1 | tail -5`
Expected: errors with `TypeError: create_app() got an unexpected keyword argument 'sign_in'`

- [ ] **Step 4: Implement**

All edits are in `fc/webapp.py`.

Replace the module docstring and the `flask` import, and add two imports:

```python
"""The Flask app: every HTTP route. The only module that knows about requests.

Two auth modes. In `local` every request acts as the local user (or a made-up
one, when dev users are on). In `google` the session names the signed-in
account, and nothing under /api/ answers without one.
"""
from __future__ import annotations

import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from flask import (Flask, Response, g, jsonify, redirect, request,
                   send_from_directory, session)
from werkzeug.exceptions import HTTPException

from .adsb import FeedError
from .airports import Airports
from .auth import GoogleSignIn, persistent_key, safe_next
from .config import Config
from .history import OPTIONAL, History, template_csv
from .mates import Mates
from .users import Users, normalize_username, validate_username
```

Below `LOCAL_HOSTS = ...`, add:

```python
# Routes a signed-in person may use before choosing a username.
USERNAME_FREE = frozenset({"/api/me", "/api/username", "/api/account/delete"})
```

Replace the start of `create_app`, from its `def` line down to and including the `mates = Mates(users, history)` line, with:

```python
def create_app(config: Config, tracker=None, airports: Airports | None = None,
               sign_in=None) -> Flask:
    google = config.auth == "google"
    app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="/static")
    # Real accounts need a key that survives restarts, or everyone is signed
    # out each time. Local mode has nothing to keep.
    app.secret_key = config.secret_key or (
        persistent_key(config.data_dir) if google else secrets.token_hex(32))
    app.permanent_session_lifetime = timedelta(days=30)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.base_url.startswith("https://"),
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )

    history = History(airports, config.db_path)
    users = Users(config.db_path)
    mates = Mates(users, history)
    if google and sign_in is None:
        sign_in = GoogleSignIn(app, config.google_client_id,
                               config.google_client_secret)
    base_host = urlsplit(config.base_url).netloc
```

Replace `current_user` with:

```python
    def current_user() -> dict | None:
        uid = session.get("uid")
        if google:
            return users.get(uid) if uid else None
        if config.dev_users and uid:
            user = users.get(uid)
            if user:
                return user
        return users.ensure_local()
```

Replace the `guard` function with:

```python
    @app.before_request
    def guard():
        if urlsplit("//" + request.host).hostname not in allowed_hosts:
            raise ApiError("unknown host", 403)
        if (google and request.method == "GET" and request.host != base_host
                and not request.path.startswith(("/api/", "/static/"))):
            # Google returns people to the configured address, and cookies do
            # not carry between localhost and 127.0.0.1, so pages move there
            # before sign-in starts.
            return redirect(config.base_url + request.full_path.rstrip("?"))
        if request.method == "POST":
            origin = urlsplit(request.headers.get("Origin", "")).netloc
            if not origin or origin != request.host:
                raise ApiError("cross-site request refused", 403)
            if not request.is_json:
                raise ApiError("requests must be JSON", 403)
        if request.path.startswith("/static/"):
            return None
        g.user = current_user()
        if request.path.startswith(("/api/", "/dev/")):
            if g.user is None:
                raise ApiError("sign in required", 401)
            if g.user["username"] is None and request.path not in USERNAME_FREE:
                raise ApiError("choose a username first", 409)
        return None
```

Replace the `index` route with:

```python
    @app.get("/")
    def index():
        if google and g.user is None:
            return redirect("/login")
        if google and g.user["username"] is None:
            return redirect("/welcome")
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/login")
    def login_page():
        if not google or g.user is not None:
            return redirect("/")
        return send_from_directory(WEB_DIR, "login.html")

    @app.get("/welcome")
    def welcome_page():
        if not google:
            return redirect("/")
        if g.user is None:
            return redirect("/login")
        if g.user["username"] is not None:
            return redirect("/")
        return send_from_directory(WEB_DIR, "welcome.html")
```

Insert immediately before the line `    # ----------------------------------------------------------- dev users`:

```python
    # ------------------------------------------------------------- sign-in
    if google:
        @app.get("/auth/login")
        def auth_login():
            session["next"] = safe_next(request.args.get("next"))
            return sign_in.begin(config.base_url + "/auth/callback")

        @app.get("/auth/callback")
        def auth_callback():
            profile = sign_in.finish()
            if profile is None:
                return redirect("/login?error=1")
            user = users.upsert_google(**profile)
            target = safe_next(session.get("next"))
            # Start a clean session: nothing from before sign-in carries over.
            session.clear()
            session["uid"] = user["id"]
            session.permanent = True
            return redirect(target)

        @app.post("/auth/logout")
        def auth_logout():
            session.clear()
            return jsonify(ok=True)

        @app.post("/api/username")
        def choose_username():
            try:
                return jsonify(users.set_username(g.user["id"],
                                                  body().get("username")))
            except ValueError as e:
                raise ApiError(str(e)) from None

        @app.post("/api/account/delete")
        def account_delete():
            if body().get("confirm") != "DELETE":
                raise ApiError("type DELETE to confirm")
            users.delete(g.user["id"])
            session.clear()
            return jsonify(ok=True)

```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: `OK`, with no warnings in the output.

- [ ] **Step 6: Commit**

```bash
git add fc/webapp.py web/login.html web/welcome.html web/style.css tests/test_signin.py
git commit -m "Add sign-in routes, sessions and the signed-out and no-username rules

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Front end — account menu and expired sessions

**Files:**
- Modify: `web/app.js`, `web/social.js`, `web/style.css`

There is no JavaScript test runner. Steps are checked with `node --check`; the browser check is in Task 6, because it needs a real sign-in.

**Interfaces:**
- Consumes: `GET /api/me` (`auth`, `username`, `name`, `picture_url`), `POST /auth/logout`, `POST /api/account/delete`.
- Produces: `avatar(person) -> string` as a global in `web/app.js`, used by the header and by `web/social.js`.

- [ ] **Step 1: Send signed-out and no-username responses to the right page**

In `web/app.js`, replace the `api` function with:

```js
async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ error: 'bad response' }));
  // A session that has expired, or an account with no username yet, cannot
  // use the app: go to the page that fixes it.
  if (res.status === 401) location.href = '/login';
  if (res.status === 409 && data.error === 'choose a username first') {
    location.href = '/welcome';
  }
  if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
  return data;
}
```

- [ ] **Step 2: Share `avatar`**

Move the `avatar` function out of `web/social.js` (delete it there) and add it to `web/app.js`, directly below the `esc` definition:

```js
function avatar(p) {
  const url = p.picture_url || '';
  // Only https pictures are ever used as an image source.
  return url.startsWith('https://')
    ? `<img class="av" src="${esc(url)}" alt="" referrerpolicy="no-referrer">`
    : `<span class="av">${esc((p.name || p.username || '?').charAt(0).toUpperCase())}</span>`;
}
```

- [ ] **Step 3: The account menu**

In `web/app.js`, replace `renderWho` with:

```js
function renderWho(me) {
  const who = $('who');
  if (me.auth === 'google') {
    who.innerHTML = `<details class="acct">
        <summary>${avatar(me)}<span class="me">@${esc(me.username)}</span></summary>
        <div class="menu">
          <button id="acct-out" class="quiet">Sign out</button>
          <button id="acct-del" class="quiet">Delete account</button>
          <form id="del-form" hidden autocomplete="off">
            <p>This removes your account and every flight you have logged.
               It cannot be undone.</p>
            <input id="del-confirm" placeholder="Type DELETE" spellcheck="false">
            <button type="submit" class="danger">Delete forever</button>
          </form>
        </div>
      </details>`;
    $('acct-out').addEventListener('click', async () => {
      try { await post('/auth/logout'); location.href = '/login'; }
      catch (err) { toast(err.message, true); }
    });
    $('acct-del').addEventListener('click', () => {
      $('del-form').hidden = false;
      $('del-confirm').focus();
    });
    $('del-form').addEventListener('submit', async e => {
      e.preventDefault();
      try {
        await post('/api/account/delete', { confirm: $('del-confirm').value });
        location.href = '/login';
      } catch (err) { toast(err.message, true); }
    });
    return;
  }
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
```

- [ ] **Step 4: Styles**

The avatar style is currently scoped to `.prow`. In `web/style.css`, change the selector `.prow .av{` to `.av{` so the header can use it, then append:

```css
.acct{position:relative}
.acct summary{display:flex;align-items:center;gap:8px;cursor:pointer;list-style:none}
.acct summary::-webkit-details-marker{display:none}
.acct .av{width:24px;height:24px;font-size:11px}
.acct .menu{position:absolute;right:0;top:calc(100% + 10px);z-index:700;width:230px;
  display:flex;flex-direction:column;gap:8px;padding:12px;background:var(--panel);
  border:1px solid var(--line);border-radius:4px;font-family:var(--sans)}
.acct .menu p{margin:0;font-size:12px;color:var(--muted);line-height:1.45}
.acct .menu form{display:flex;flex-direction:column;gap:8px}
.acct .menu form[hidden]{display:none}
.acct .menu input{width:100%}
button.danger{background:#2a1512;border-color:#4a231d;color:var(--red)}
button.danger:hover{background:#3a1b16}
```

- [ ] **Step 5: Check syntax and that nothing regressed**

Run: `node --check web/app.js && node --check web/social.js && grep -c "function avatar" web/app.js web/social.js`
Expected: no syntax error; `web/app.js:1` and `web/social.js:0`.

Run: `.venv/bin/python -m unittest discover -s tests -t .`
Expected: `OK`.

Start the `wingmates-dev` launch configuration and open `http://localhost:8817`: the header still shows `@you` and the switch box, the Social tab still shows letter avatars, and there are no console errors. This confirms local mode is untouched.

- [ ] **Step 6: Commit**

```bash
git add web/app.js web/social.js web/style.css
git commit -m "Add the account menu and handle expired sessions in the page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Run it, document it, and sign in for real

**Files:**
- Create: `docs/google-sign-in-setup.md`
- Modify: `run.py`, `.claude/launch.json`, `README.md`

- [ ] **Step 1: Open the right address in `google` mode**

In `run.py`, replace the line `    url = f"http://{args.host}:{args.port}"` with:

```python
    # With sign-in on, the browser must use the address Google returns to.
    url = cfg.base_url if cfg.auth == "google" else f"http://{args.host}:{args.port}"
```

and add, directly after the line that prints `data`:

```python
    print(f"  auth   {'Google sign-in' if cfg.auth == 'google' else 'local, no sign-in'}")
```

- [ ] **Step 2: Add a launch entry**

In `.claude/launch.json`, add a third configuration:

```json
    {
      "name": "wingmates-google",
      "runtimeExecutable": "env",
      "runtimeArgs": ["WINGMATES_AUTH=google", ".venv/bin/python", "run.py",
                      "--no-browser"],
      "port": 8817
    }
```

- [ ] **Step 3: Write the setup guide**

Create `docs/google-sign-in-setup.md`:

```markdown
# Setting up Google sign-in

Wingmates signs people in with Google. This takes about ten minutes, is free,
and needs no billing account.

## 1. Create a project

1. Go to https://console.cloud.google.com and sign in.
2. Open the project picker, choose **New Project**, name it `Wingmates`.
3. Make sure that project is selected.

## 2. Set up the consent screen

1. Open **Google Auth Platform** and press **Get started**.
2. App name `Wingmates`, your email for support and contact, audience
   **External**.

## 3. Add test users

A new app is in **Testing** mode: only listed people can sign in.

1. Open **Audience**.
2. Under **Test users**, add your own Google address and each friend's.

An app that uses only the basic sign-in scopes does not have to be verified
by Google, so it can be published later without a review.

## 4. Create the client

1. Open **Clients**, press **Create Client**, type **Web application**.
2. Under **Authorized redirect URIs** add, with no trailing slash:
   `http://localhost:8817/auth/callback`
3. Press **Create**.

Add the hosted address here as well when the app is deployed, in the form
`https://your-host/auth/callback`.

## 5. Save the secret

Google shows the client secret once. Press **Download JSON** and move the file
into the data folder:

    mv ~/Downloads/client_secret_*.json ~/.wingmates/google-client.json
    chmod 600 ~/.wingmates/google-client.json

That folder is outside the repository, so the secret cannot be committed.
On a server, set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` instead.

## 6. Start with sign-in on

    WINGMATES_AUTH=google .venv/bin/python run.py

Open `http://localhost:8817`, not `127.0.0.1`: the address must match the
redirect address registered above.

## Moving your existing flights

Flights logged before sign-in belong to the local user `@you`, which is not a
Google account and is not merged with one. To bring them across: start without
`WINGMATES_AUTH`, press **Export** in My flights, then start with sign-in,
sign in, and use **Import CSV**.
```

- [ ] **Step 4: Update the README**

In the opening section, replace the paragraph that begins `There is no sign-in yet:` with:

```markdown
By default there is no sign-in: on your own machine every request acts as one
local user, `@you`. To have people sign in with Google, see
[docs/google-sign-in-setup.md](docs/google-sign-in-setup.md).
```

Add these rows to the Settings table:

```markdown
| `WINGMATES_AUTH` | `local` | `google` requires sign-in. Live then defaults to off and dev users are ignored. |
| `WINGMATES_BASE_URL` | `http://localhost:8817` | The address people use. Google returns sign-ins here, and the app only answers to this host and the local names. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | from `~/.wingmates/google-client.json` | The Google client, when not using the downloaded file. |
| `SECRET_KEY` | generated, kept in `~/.wingmates/secret_key` | Signs session cookies. |
```

In the Layout block add `fc/auth.py              Google sign-in`, `web/login.html, welcome.html   sign-in and choose-a-username pages`, and change the `requirements.txt` line to `requirements.txt        Flask, Authlib, requests`.

In the API block add:

```
GET  /auth/login, /auth/callback     Google sign-in            (google mode)
POST /auth/logout                    sign out                  (google mode)
POST /api/username {username}        choose a username, once   (google mode)
POST /api/account/delete {confirm}   delete your account       (google mode)
```

In "Not built yet", replace `Sign-in and hosting.` with `Hosting.` and remove the sentence about made-up users being the only way to try the Social tab.

- [ ] **Step 5: Save the owner's local flights before switching modes**

With the normal `wingmates` configuration running:

```bash
curl -s http://localhost:8817/api/history/export.csv -o ~/Downloads/wingmates-flights.csv
cat ~/Downloads/wingmates-flights.csv
```

Expected: the header line and one line per existing flight.

- [ ] **Step 6: Start in `google` mode and check everything that needs no Google account**

Stop the running server and start the `wingmates-google` configuration.

- `curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://localhost:8817/` prints `302 http://localhost:8817/login`.
- `curl -s http://localhost:8817/api/me` prints `{"error":"sign in required"}`.
- `curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://127.0.0.1:8817/` prints `302 http://localhost:8817/`.
- `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8817/auth/login` prints `302`, and the `Location` header (`curl -sI`) points at `accounts.google.com` with `redirect_uri=http%3A%2F%2Flocalhost%3A8817%2Fauth%2Fcallback` and a `scope` naming `openid`, `email` and `profile` and nothing else.
- `ls -l ~/.wingmates/secret_key` shows mode `-rw-------`.
- The sign-in page at `http://localhost:8817/login` renders with one **Continue with Google** button and no console errors.

- [ ] **Step 7: Ask the owner to sign in**

This step cannot be automated: it needs the owner's Google account. Stop and ask them to open `http://localhost:8817`, press **Continue with Google**, and confirm:

1. Google shows a consent screen naming Wingmates, and returns to the app.
2. The choose-a-username page appears. A taken or malformed name shows an error; a good one opens the app.
3. The header shows their picture and `@username`. The menu has Sign out and Delete account.
4. **Import CSV** with `~/Downloads/wingmates-flights.csv` brings their flights back.
5. Sign out returns to the sign-in page; signing in again goes straight to the app with the same username and flights.
6. Stopping and restarting the server leaves them signed in.

If Google shows `redirect_uri_mismatch`, the redirect address in the console does not exactly match `http://localhost:8817/auth/callback`. If it shows `access_denied`, their address is not in the test users list.

- [ ] **Step 8: Commit**

```bash
git add run.py .claude/launch.json README.md docs/google-sign-in-setup.md
git commit -m "Document Google sign-in and add a launch entry for it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
