# Free Hosting on Vercel + Turso Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Wingmates for free: the app on Vercel's Hobby plan, its data in a Turso database.

**Architecture:** Vercel has no persistent disk, so the hosted app keeps its data in Turso, a hosted database that speaks SQLite's dialect. A small client, `fc/turso.py`, sends SQL to Turso's HTTP API and returns results shaped like `sqlite3`'s, so the three stores run unchanged against either a local file or Turso. `fc.db.connect()` picks between them. Local use is unaffected. Tests run the existing store suites a second time through the Turso client, against a stand-in server that is itself backed by SQLite.

**Tech Stack:** Python 3.13, Flask, `requests`, Turso SQL-over-HTTP (`POST /v2/pipeline`), Vercel Python runtime.

**Spec:** `docs/superpowers/specs/2026-10-01-mates-and-wingspans-design.md`

The Render route from the previous plan stays in the repository, unused, as the paid alternative.

## Global Constraints

- No new dependencies. The Turso client uses `requests`, already required.
- Local behaviour is unchanged: with no Turso settings the app uses the SQLite file exactly as before.
- All tests are offline. Nothing in the test suite contacts Turso, Vercel or Google. The stand-in Turso server runs in-process.
- Run tests with `.venv/bin/python -m unittest discover -s tests -t .`
- The Turso token is a secret: never printed, logged, committed, placed in a `repr`, or included in an exception message.
- The stand-in server runs with foreign keys **off**. Store code must not rely on `ON DELETE CASCADE`.
- A database failure of any kind surfaces as a `sqlite3.Error` subclass, whichever backend is in use: `sqlite3.IntegrityError` for a constraint violation, `sqlite3.OperationalError` otherwise.
- A read outside a transaction costs exactly one HTTP request.
- A CSV import holds at most 5,000 flights.
- On Vercel the filesystem is read-only: the hosted app must not write any file. `SECRET_KEY` is therefore required whenever Turso is in use.
- Static assets (`.js`, `.css`) live in `public/static/` and are served at `/static/`. HTML pages stay in `web/` and are served only by the app's routes.
- End every commit message with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

Each of these has a test in the task named.

1. **Deleting an account when the database does not enforce foreign keys.** Expected: the person's flights, requests and mate pairs are gone anyway. Task 2.
2. **A CSV import of several thousand flights.** Turso gives a transaction five seconds. Expected: the import is sent in a few batched requests, not one per row, and a file over the cap is refused with a clear message. Task 3.
3. **Turso unreachable, slow, or answering with an error status.** Expected: a `sqlite3.OperationalError`, a 503 from `/healthz`, and no token in any message. Task 1 and Task 4.
4. **A failed statement in the middle of a transaction.** Expected: the transaction is rolled back and nothing from it is kept. Task 1.
5. **A hosted start-up without `SECRET_KEY`.** On Vercel the fallback of writing a key file cannot work. Expected: a clear refusal at start, not a crash on the first sign-in. Task 4.

## File Structure

| File | Responsibility |
|---|---|
| `fc/turso.py` (new) | `Turso` (address + token) and `TursoConnection`: SQL over HTTP, shaped like `sqlite3`. |
| `fc/db.py` (modify) | `connect()` and `init()` accept a file path or a `Turso`; `readable()` for the health check. |
| `fc/users.py`, `fc/history.py`, `fc/mates.py` (modify) | Take a database, not a path; explicit account deletion; batched import. |
| `fc/config.py` (modify) | Turso settings; `Config.database`; base URL from Vercel. |
| `fc/webapp.py`, `fc/hosted.py` (modify) | Use `config.database`; static folder; the `SECRET_KEY` rule. |
| `wsgi.py` (new, repository root) | The entry point Vercel looks for. |
| `public/static/` (new) | The `.js` and `.css` files, moved from `web/`. |
| `.python-version` (new) | Python 3.13 for Vercel. |
| `tools/save_turso.py`, `tools/turso_check.py` (new) | Save Turso settings without pasting them into a chat; check a real database. |
| `docs/deploy-vercel.md` (new), `README.md`, `Dockerfile` (modify) | Guide; layout changes. |
| `tests/fake_turso.py` (new) | Stand-in Turso server. |
| `tests/test_turso.py`, `tests/test_on_turso.py` (new) | Client tests; the store suites re-run on Turso. |
| `tests/helpers.py` and existing test files (modify) | One place that decides which database a test uses. |

---

### Task 1: The Turso client

**Files:**
- Create: `fc/turso.py`, `tests/fake_turso.py`, `tests/test_turso.py`

**Interfaces:**
- Consumes: Turso's HTTP API. Request: `POST <url>/v2/pipeline`, header `Authorization: Bearer <token>`, body `{"baton": <optional>, "requests": [{"type": "execute", "stmt": {"sql": ..., "args": [...]}}, ..., {"type": "close"}]}`. Values are `{"type": "null"}`, `{"type": "integer", "value": "<digits>"}`, `{"type": "float", "value": <number>}`, `{"type": "text", "value": "..."}`. Response: `{"baton": <string or null>, "base_url": <string or null>, "results": [{"type": "ok", "response": {"type": "execute", "result": {"cols": [{"name": ...}], "rows": [[value, ...]], "affected_row_count": <int>, "last_insert_rowid": "<digits>" or null}}} or {"type": "error", "error": {"message": ..., "code": ...}}]}`. Leaving out the `close` request keeps the connection open and returns a `baton` to send with the next request.
- Produces:
  - `fc.turso.Turso(url: str, token: str)` — frozen dataclass; `url` normalised to `https://...` with no trailing slash; `token` excluded from `repr`. Raises `ValueError` on a bad URL or empty token.
  - `fc.turso.send(database: Turso, payload: dict, base_url: str | None = None) -> dict` — one HTTP request. Raises `sqlite3.OperationalError` on any transport failure or non-200 status.
  - `fc.turso.TursoConnection(database: Turso)` with `execute(sql, params=()) -> Result`, `executemany(sql, rows) -> None`, `batch(statements: list[str]) -> None`, `commit()`, `rollback()`, `close()`, and context-manager use that commits on success and rolls back on an exception.
  - `Result` with `fetchone()`, `fetchall()`, iteration, `lastrowid`, `rowcount`. Rows are tuples that also accept a column name: `row["id"]`, `row[0]`.

- [ ] **Step 1: Create the branch**

```bash
cd ~/flighty-clone
git checkout -b free-hosting
git add docs/superpowers && git commit -m "Add the free-hosting plan and spec amendments

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 2: Write the stand-in server**

Create `tests/fake_turso.py`:

```python
"""A stand-in for Turso, for tests. It answers the same JSON requests the real
service does, from a SQLite file, so the client and the stores can be
exercised offline.

Foreign keys are left off on purpose. The real service may or may not enforce
them, so code that passes here cannot be relying on ON DELETE CASCADE.

Value encoding is written out again here rather than imported from the client:
a shared helper would make both sides wrong in the same way.
"""
import copy
import secrets
import sqlite3
import threading


def _decode(arg):
    kind = arg["type"]
    if kind == "null":
        return None
    if kind == "integer":
        return int(arg["value"])
    if kind == "float":
        return float(arg["value"])
    if kind == "text":
        return arg["value"]
    raise AssertionError(f"unexpected argument type {kind!r}")


def _encode(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    return {"type": "text", "value": str(value)}


class FakeTurso:
    def __init__(self, file):
        self.file = file
        self.calls = []              # every payload received, in order
        self._streams = {}           # baton -> open connection
        self._lock = threading.Lock()

    def statements(self):
        """Every SQL string received, flattened, for assertions."""
        return [r["stmt"]["sql"] for call in self.calls
                for r in call["requests"] if r["type"] == "execute"]

    def send(self, database, payload, base_url=None):
        with self._lock:
            self.calls.append(copy.deepcopy(payload))
            baton = payload.get("baton")
            conn = self._streams.pop(baton) if baton else None
        if baton and conn is None:
            raise sqlite3.OperationalError("database returned HTTP 400")
        if conn is None:
            # isolation_level=None: no implicit transactions, like the service.
            conn = sqlite3.connect(self.file, isolation_level=None,
                                   check_same_thread=False, timeout=10)
        results, closed = [], False
        for request in payload["requests"]:
            if request["type"] == "close":
                conn.close()
                closed = True
                results.append({"type": "ok", "response": {"type": "close"}})
                continue
            stmt = request["stmt"]
            try:
                cur = conn.execute(stmt["sql"],
                                   [_decode(a) for a in stmt.get("args", [])])
                rows = cur.fetchall() if cur.description else []
                results.append({"type": "ok", "response": {
                    "type": "execute",
                    "result": {
                        "cols": [{"name": d[0], "decltype": None}
                                 for d in cur.description or []],
                        "rows": [[_encode(v) for v in row] for row in rows],
                        "affected_row_count": max(cur.rowcount, 0),
                        "last_insert_rowid": (str(cur.lastrowid)
                                              if cur.lastrowid else None),
                    }}})
            except sqlite3.IntegrityError as e:
                results.append({"type": "error", "error": {
                    "message": str(e), "code": "SQLITE_CONSTRAINT"}})
            except sqlite3.Error as e:
                results.append({"type": "error", "error": {
                    "message": str(e), "code": "SQLITE_ERROR"}})
        new_baton = None
        if not closed:
            new_baton = secrets.token_hex(8)
            with self._lock:
                self._streams[new_baton] = conn
        return {"baton": new_baton, "base_url": None, "results": results}
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_turso.py`:

```python
"""Turso client tests, against the stand-in server. Offline."""
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc import turso
from fc.turso import Turso, TursoConnection
from tests.fake_turso import FakeTurso


class TestTursoAddress(unittest.TestCase):

    def test_the_url_is_normalised(self):
        for raw in ("libsql://wm-brett.turso.io", "https://wm-brett.turso.io/",
                    "  libsql://wm-brett.turso.io  "):
            self.assertEqual(Turso(raw, "t").url, "https://wm-brett.turso.io")

    def test_bad_settings_are_refused(self):
        for url, token in (("http://x.turso.io", "t"), ("x.turso.io", "t"),
                           ("", "t"), ("libsql://x.turso.io", "")):
            with self.assertRaises(ValueError):
                Turso(url, token)

    def test_the_token_is_not_in_the_repr(self):
        self.assertNotIn("s3cret", repr(Turso("libsql://x.turso.io", "s3cret")))


class TursoCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fake = FakeTurso(Path(tmp.name) / "remote.db")
        patcher = mock.patch("fc.turso.send", self.fake.send)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db = Turso("libsql://wm-test.turso.io", "tok")
        with closing(TursoConnection(self.db)) as c:
            c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY,"
                      " name TEXT UNIQUE, n REAL)")
        self.fake.calls.clear()

    def conn(self):
        return closing(TursoConnection(self.db))

    def names(self):
        with self.conn() as c:
            return [r["name"] for r in c.execute("SELECT name FROM t ORDER BY id")]


class TestReads(TursoCase):

    def test_a_read_is_one_self_contained_request(self):
        with self.conn() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM t").fetchone()[0], 0)
        self.assertEqual(len(self.fake.calls), 1)
        self.assertNotIn("baton", self.fake.calls[0])
        self.assertEqual(self.fake.calls[0]["requests"][-1], {"type": "close"})

    def test_values_and_rows_round_trip(self):
        with self.conn() as c, c:
            cur = c.execute("INSERT INTO t (name, n) VALUES (?, ?)", ("zoë", 1.5))
            self.assertEqual((cur.lastrowid, cur.rowcount), (1, 1))
            c.execute("INSERT INTO t (id, name, n) VALUES (?, ?, ?)",
                      (2 ** 40, None, None))
        with self.conn() as c:
            rows = c.execute("SELECT id, name, n FROM t ORDER BY id").fetchall()
        self.assertEqual([tuple(r) for r in rows],
                         [(1, "zoë", 1.5), (2 ** 40, None, None)])
        self.assertEqual((rows[0]["name"], rows[0][1], rows[0]["n"]),
                         ("zoë", "zoë", 1.5))
        self.assertIsInstance(rows[1]["id"], int)

    def test_fetchone_on_nothing_is_none_and_results_iterate(self):
        with self.conn() as c:
            self.assertIsNone(c.execute("SELECT * FROM t").fetchone())
            self.assertEqual(list(c.execute("SELECT * FROM t")), [])


class TestTransactions(TursoCase):

    def test_a_write_opens_a_transaction_that_commit_ends(self):
        with self.conn() as c, c:
            c.execute("INSERT INTO t (name) VALUES (?)", ("a",))
            c.execute("INSERT INTO t (name) VALUES (?)", ("b",))
        self.assertEqual(self.fake.statements(),
                         ["BEGIN", "INSERT INTO t (name) VALUES (?)",
                          "INSERT INTO t (name) VALUES (?)", "COMMIT"])
        self.assertEqual(self.fake.calls[-1]["requests"][-1], {"type": "close"})
        self.assertIn("baton", self.fake.calls[1])
        self.assertEqual(self.names(), ["a", "b"])

    def test_an_exception_rolls_the_transaction_back(self):
        with self.assertRaises(RuntimeError):
            with self.conn() as c, c:
                c.execute("INSERT INTO t (name) VALUES (?)", ("a",))
                raise RuntimeError("boom")
        self.assertEqual(self.fake.statements()[-1], "ROLLBACK")
        self.assertEqual(self.names(), [])

    def test_a_failed_statement_mid_transaction_keeps_nothing(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.conn() as c, c:
                c.execute("INSERT INTO t (name) VALUES (?)", ("a",))
                c.execute("INSERT INTO t (name) VALUES (?)", ("a",))
        self.assertEqual(self.names(), [])

    def test_closing_without_commit_rolls_back(self):
        with self.conn() as c:
            c.execute("INSERT INTO t (name) VALUES (?)", ("a",))
        self.assertEqual(self.names(), [])

    def test_reads_inside_a_transaction_see_its_writes(self):
        with self.conn() as c, c:
            c.execute("INSERT INTO t (name) VALUES (?)", ("a",))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM t").fetchone()[0], 1)

    def test_errors_are_sqlite3_errors(self):
        with self.conn() as c:
            with self.assertRaises(sqlite3.OperationalError):
                c.execute("SELECT * FROM missing")
        with self.conn() as c, c:
            c.execute("INSERT INTO t (name) VALUES (?)", ("a",))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.conn() as c, c:
                c.execute("INSERT INTO t (name) VALUES (?)", ("a",))

    def test_executemany_batches_rows_into_few_requests(self):
        rows = [(f"n{i}",) for i in range(450)]
        with self.conn() as c, c:
            c.executemany("INSERT INTO t (name) VALUES (?)", rows)
        # 200 + 200 + 50, then the commit: four requests for 450 rows.
        self.assertEqual(len(self.fake.calls), 4)
        self.assertEqual(len(self.names()), 450)

    def test_executemany_is_all_or_nothing(self):
        rows = [("a",), ("b",), ("a",)]
        with self.assertRaises(sqlite3.IntegrityError):
            with self.conn() as c, c:
                c.executemany("INSERT INTO t (name) VALUES (?)", rows)
        self.assertEqual(self.names(), [])

    def test_batch_runs_several_statements_in_one_request(self):
        with self.conn() as c:
            c.batch(["CREATE TABLE IF NOT EXISTS a (x)",
                     "CREATE TABLE IF NOT EXISTS b (x)"])
        self.assertEqual(len(self.fake.calls), 1)
        with self.conn() as c:
            c.execute("SELECT * FROM a")
            c.execute("SELECT * FROM b")


class TestTransport(unittest.TestCase):
    """The real send(), with the HTTP library stubbed."""

    def setUp(self):
        self.db = Turso("libsql://wm-test.turso.io", "s3cret-token")

    def reply(self, status=200, body=None):
        r = mock.Mock()
        r.status_code = status
        r.json.return_value = body or {"baton": None, "results": []}
        return r

    def test_it_posts_to_the_pipeline_endpoint_with_the_token(self):
        with mock.patch.object(turso._session, "post",
                               return_value=self.reply()) as post:
            turso.send(self.db, {"requests": []})
        (url,), kwargs = post.call_args
        self.assertEqual(url, "https://wm-test.turso.io/v2/pipeline")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer s3cret-token")
        self.assertEqual(kwargs["json"], {"requests": []})
        self.assertGreater(kwargs["timeout"], 0)

    def test_it_follows_a_base_url_given_by_the_service(self):
        with mock.patch.object(turso._session, "post",
                               return_value=self.reply()) as post:
            turso.send(self.db, {"requests": []}, base_url="https://other.turso.io/")
        self.assertEqual(post.call_args[0][0], "https://other.turso.io/v2/pipeline")

    def test_every_kind_of_failure_is_an_operational_error_without_the_token(self):
        failures = [dict(side_effect=requests.ConnectionError("s3cret-token")),
                    dict(side_effect=requests.Timeout()),
                    dict(return_value=self.reply(401)),
                    dict(return_value=self.reply(500))]
        for outcome in failures:
            with mock.patch.object(turso._session, "post", **outcome):
                with self.assertRaises(sqlite3.OperationalError) as cm:
                    turso.send(self.db, {"requests": []})
            self.assertNotIn("s3cret-token", str(cm.exception))

    def test_a_connection_survives_nothing_after_a_transport_failure(self):
        conn = TursoConnection(self.db)
        with mock.patch.object(turso._session, "post",
                               side_effect=requests.ConnectionError()):
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("INSERT INTO t (name) VALUES (?)", ("a",))
            conn.close()                         # must not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 4: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_turso 2>&1 | tail -4`
Expected: `ModuleNotFoundError: No module named 'fc.turso'`

- [ ] **Step 5: Implement**

Create `fc/turso.py`:

```python
"""A small client for Turso's SQL-over-HTTP API.

Turso hosts a database that speaks SQLite's dialect. This sends SQL to it and
returns results shaped like the standard library's sqlite3 module, so the
stores can run against a local file or against Turso without knowing which.

Each HTTP request carries a list of statements. Ending the list with "close"
makes the request self-contained. Leaving it off keeps the connection open on
Turso's side and returns a "baton" to present with the next request, which is
how a transaction spans several requests.

Transactions follow sqlite3's own rule: the first write on a connection opens
one, and it ends with commit() or rollback(). A read outside a transaction is
a single self-contained request.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import requests

TIMEOUT_S = 10
CHUNK = 200                     # statements per request in executemany()
_WRITES = ("INSERT", "UPDATE", "DELETE", "REPLACE")

_session = requests.Session()


@dataclass(frozen=True)
class Turso:
    """Where a Turso database is, and the token that opens it."""
    url: str
    token: str = field(repr=False)

    def __post_init__(self):
        url = (self.url or "").strip().rstrip("/")
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        if not url.startswith("https://") or len(url) <= len("https://"):
            raise ValueError(
                "TURSO_DATABASE_URL must start with libsql:// or https://")
        if not self.token:
            raise ValueError("TURSO_AUTH_TOKEN is empty")
        object.__setattr__(self, "url", url)


def send(database: Turso, payload: dict, base_url: str | None = None) -> dict:
    """One request to Turso. Any failure to get an answer is an
    OperationalError, described by its kind only: the exception text of an
    HTTP library can contain the request, and the request contains the token."""
    url = (base_url or database.url).rstrip("/") + "/v2/pipeline"
    try:
        reply = _session.post(
            url, json=payload, timeout=TIMEOUT_S,
            headers={"Authorization": f"Bearer {database.token}"})
    except requests.RequestException as e:
        raise sqlite3.OperationalError(
            f"database unreachable: {type(e).__name__}") from None
    if reply.status_code != 200:
        raise sqlite3.OperationalError(
            f"database returned HTTP {reply.status_code}")
    return reply.json()


def _encode(value) -> dict:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    return {"type": "text", "value": str(value)}


def _decode(cell: dict):
    kind = cell["type"]
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
    if kind == "text":
        return cell["value"]
    raise sqlite3.OperationalError(f"unsupported value type {kind!r}")


def _error(err: dict) -> sqlite3.Error:
    message = err.get("message", "database error")
    if str(err.get("code", "")).startswith("SQLITE_CONSTRAINT"):
        return sqlite3.IntegrityError(message)
    return sqlite3.OperationalError(message)


class Row(tuple):
    """A result row: a tuple that also accepts a column name."""

    def __new__(cls, values, index):
        row = super().__new__(cls, values)
        row._index = index
        return row

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._index[key])
        return tuple.__getitem__(self, key)

    def keys(self):
        return list(self._index)


class Result:
    def __init__(self, result: dict):
        index = {c["name"]: i for i, c in enumerate(result.get("cols", []))}
        self._rows = [Row([_decode(c) for c in row], index)
                      for row in result.get("rows", [])]
        self._next = 0
        last = result.get("last_insert_rowid")
        self.lastrowid = int(last) if last is not None else None
        self.rowcount = result.get("affected_row_count", 0)

    def fetchone(self):
        if self._next >= len(self._rows):
            return None
        row = self._rows[self._next]
        self._next += 1
        return row

    def fetchall(self):
        rest = self._rows[self._next:]
        self._next = len(self._rows)
        return rest

    def __iter__(self):
        return iter(self.fetchall())


class TursoConnection:
    def __init__(self, database: Turso):
        self._database = database
        self._baton = None
        self._base_url = None
        self._tx = False

    def _run(self, statements, close: bool) -> list:
        """Send statements in one request. Returns one item per statement: a
        result dict, or the exception that statement produced. Errors come
        back as values so the caller can update its state before raising."""
        reqs = [{"type": "execute",
                 "stmt": {"sql": sql, "args": [_encode(a) for a in args]}}
                for sql, args in statements]
        if close:
            reqs.append({"type": "close"})
        payload = {"requests": reqs}
        if self._baton:
            payload["baton"] = self._baton
        try:
            reply = send(self._database, payload, self._base_url)
        except sqlite3.Error:
            # No answer: whatever was open on the far side is gone for us.
            self._baton, self._tx = None, False
            raise
        self._baton = None if close else reply.get("baton")
        self._base_url = reply.get("base_url") or self._base_url
        out = []
        for item in reply["results"][:len(statements)]:
            out.append(_error(item["error"]) if item["type"] == "error"
                       else item["response"]["result"])
        return out

    @staticmethod
    def _first_error(results):
        for r in results:
            if isinstance(r, Exception):
                raise r

    def execute(self, sql: str, params=()) -> Result:
        verb = sql.lstrip().split(None, 1)[0].upper()
        params = tuple(params)
        if verb in _WRITES and not self._tx:
            begin, result = self._run([("BEGIN", ()), (sql, params)], close=False)
            if isinstance(begin, Exception):
                raise begin
            self._tx = True
        elif self._tx:
            (result,) = self._run([(sql, params)], close=False)
        else:
            (result,) = self._run([(sql, params)], close=True)
        if isinstance(result, Exception):
            raise result
        return Result(result)

    def executemany(self, sql: str, rows) -> None:
        """Run one statement for many rows, a chunk per request, all inside
        the connection's transaction."""
        rows = [tuple(r) for r in rows]
        for start in range(0, len(rows), CHUNK):
            statements = [(sql, r) for r in rows[start:start + CHUNK]]
            if not self._tx:
                statements.insert(0, ("BEGIN", ()))
            results = self._run(statements, close=False)
            if not isinstance(results[0], Exception):
                self._tx = True
            self._first_error(results)

    def batch(self, statements: list[str]) -> None:
        """Several statements with no arguments in one self-contained
        request. For schema setup."""
        self._first_error(self._run([(s, ()) for s in statements], close=True))

    def commit(self) -> None:
        if self._tx:
            (result,) = self._run([("COMMIT", ())], close=True)
            self._tx = False
            if isinstance(result, Exception):
                raise result

    def rollback(self) -> None:
        if self._tx:
            self._tx = False
            try:
                self._run([("ROLLBACK", ())], close=True)
            except sqlite3.Error:
                pass          # the far side drops an abandoned transaction itself

    def close(self) -> None:
        self.rollback()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_turso -v 2>&1 | tail -6`
Expected: 19 tests, `OK`.

- [ ] **Step 7: Commit**

```bash
git add fc/turso.py tests/fake_turso.py tests/test_turso.py
git commit -m "Add a Turso client shaped like sqlite3

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Stores on either database

**Files:**
- Modify: `fc/db.py`, `fc/users.py`, `fc/history.py`, `fc/mates.py`, `fc/config.py`, `fc/webapp.py`, `tests/helpers.py`, `tests/test_users.py`, `tests/test_history.py`, `tests/test_mates.py`, `tests/test_signin.py`, `tests/test_config.py`
- Create: `tests/test_on_turso.py`

**Interfaces:**
- Consumes: `Turso`, `TursoConnection` from Task 1.
- Produces:
  - `fc.db.connect(database: Path | Turso)` and `fc.db.init(database: Path | Turso)`.
  - `fc.db.readable(database) -> bool` — whether the `users` table can be read; never creates a file.
  - `Users(database)`, `History(airports=None, database=DB_FILE)`; attribute `.database` replaces `.path` on `Users`, `History`, `UserHistory` and `Mates`.
  - `Users.delete` removes the user's flights, requests and mate pairs itself.
  - `Config.turso: Turso | None`, read from `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`, or from `<data_dir>/turso.json` (`{"url": ..., "token": ...}`) when `WINGMATES_USE_TURSO=1`. `Config.database -> Path | Turso` is `turso` if set, else `db_path`.
  - `tests.helpers.stores(case)` uses Turso through the stand-in when the test class has `on_turso = True`, and sets `case.database`.

- [ ] **Step 1: Rename `path` to `database` in the stores and their tests**

```bash
sed -i '' -e 's/self\.path/self.database/g' -e 's/history\.path/history.database/g' fc/users.py fc/history.py fc/mates.py
sed -i '' -e 's/def __init__(self, path: Path):/def __init__(self, database):/' -e 's/self\.database = path/self.database = database/' -e 's/init(path)/init(database)/' fc/users.py
sed -i '' -e 's/path: Path = DB_FILE):/database=DB_FILE):/' -e 's/self\.database = path/self.database = database/' -e 's/init(path)/init(database)/' fc/history.py
sed -i '' -e 's/self\.h\.path/self.h.database/g' -e 's/self\.history\.path/self.history.database/g' tests/test_history.py tests/test_mates.py
grep -n "\.path\b" fc/users.py fc/history.py fc/mates.py tests/test_history.py tests/test_mates.py | grep -v "sys.path"
.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -2
```

Expected: the `grep` prints nothing, and the suite is `OK`. This step changes names only.

- [ ] **Step 2: Route test fixtures through one helper**

Replace `tests/helpers.py` with:

```python
"""Shared fixtures for store and web tests. Offline."""
import tempfile
from pathlib import Path
from unittest import mock

from fc.airports import Airports
from fc.history import History
from fc.turso import Turso
from fc.users import Users
from tests.fake_turso import FakeTurso

AIRPORTS_CSV = """iata,icao,name,city,country,lat,lon,size
ATL,KATL,Hartsfield Jackson Atlanta International Airport,Atlanta,US,33.6367,-84.4281,3
JFK,KJFK,John F. Kennedy International Airport,New York,US,40.6394,-73.7793,3
LHR,EGLL,London Heathrow Airport,London,GB,51.4707,-0.4599,3
NRT,RJAA,Narita International Airport,Narita,JP,35.7686,140.3887,3
"""


def temp_dir(case) -> Path:
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    return Path(tmp.name)


def database(case, d: Path):
    """The database a test uses: a SQLite file, or, for a test class with
    `on_turso = True`, Turso through the stand-in server."""
    if not getattr(case, "on_turso", False):
        return d / "flights.db"
    case.fake = FakeTurso(d / "remote.db")
    patcher = mock.patch("fc.turso.send", case.fake.send)
    patcher.start()
    case.addCleanup(patcher.stop)
    return Turso("libsql://wm-test.turso.io", "test-token")


def stores(case):
    """A temp data directory with an airport table, a History and a Users,
    cleaned up when the test case finishes. Sets case.database."""
    d = temp_dir(case)
    (d / "airports.csv").write_text(AIRPORTS_CSV)
    airports = Airports(d / "airports.csv")
    case.database = database(case, d)
    return d, airports, History(airports, case.database), Users(case.database)
```

In `tests/test_users.py`, replace `UsersCase` with:

```python
class UsersCase(unittest.TestCase):
    def setUp(self):
        self.users = Users(database(self, temp_dir(self)))
```

and add `from tests.helpers import database, temp_dir` to its imports. The `import tempfile` line there is now unused; remove it.

In `tests/test_history.py`, replace `HistoryCase.setUp` with:

```python
    def setUp(self):
        d = temp_dir(self)
        (d / "airports.csv").write_text(AIRPORTS_CSV)
        self.airports = Airports(d / "airports.csv")
        self.database = database(self, d)
        self.store = History(self.airports, self.database)
        self.users = Users(self.database)
        self.uid = self.users.create("Ann", "ann")["id"]
        self.h = self.store.for_user(self.uid)
```

add `from tests.helpers import database, temp_dir` to its imports, and remove its now-unused `import tempfile`.

In `tests/test_signin.py`, in `SignInCase.setUp`, pass the database to `Config` by adding one argument to the `Config(...)` call:

```python
                   turso=self.database if isinstance(self.database, Turso) else None,
```

and add `from fc.turso import Turso` to its imports.

- [ ] **Step 3: Write the failing tests**

Create `tests/test_on_turso.py`:

```python
"""The store and sign-in suites again, with Turso as the database.

Every test class listed here is re-run with `on_turso = True`, which makes the
shared fixtures hand out a Turso database served by the stand-in. The tests
themselves are unchanged: what passes on a SQLite file must pass on Turso.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.turso import Turso
from tests import test_history, test_mates, test_signin, test_users

SUITES = {
    test_users: ["TestUsers", "TestGoogleAccounts", "TestSetUsername",
                 "TestSessionEpoch"],
    test_history: ["TestAdd", "TestUpdate", "TestStats", "TestImport",
                   "TestIsolation", "TestExport"],
    test_mates: ["TestCard", "TestRequests", "TestMates", "TestPrivacy",
                 "TestDeclineStaysSecret"],
    test_signin: ["TestSignIn", "TestSessions", "TestAccountDelete",
                  "TestTwoPeople"],
}

for module, names in SUITES.items():
    for name in names:
        globals()[f"{name}OnTurso"] = type(
            f"{name}OnTurso", (getattr(module, name),), {"on_turso": True})


class TestTheFixtureReallyUsesTurso(unittest.TestCase):
    on_turso = True

    def test_requests_reach_the_stand_in_and_no_file_is_made(self):
        from tests.helpers import stores
        d, _, history, users = stores(self)
        self.assertIsInstance(self.database, Turso)
        uid = users.create("Ann", "ann")["id"]
        history.for_user(uid).add("2024-03-09", "ATL", "LHR")
        self.assertGreater(len(self.fake.calls), 0)
        self.assertFalse((d / "flights.db").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

Add to `tests/test_config.py`, above the `if __name__` line:

```python
class TestTursoSettings(unittest.TestCase):

    def test_without_settings_the_database_is_the_local_file(self):
        c = Config.from_env({})
        self.assertIsNone(c.turso)
        self.assertEqual(c.database, c.db_path)

    def test_environment_settings_select_turso(self):
        c = Config.from_env({"TURSO_DATABASE_URL": "libsql://wm-b.turso.io",
                             "TURSO_AUTH_TOKEN": "s3cret-token"})
        self.assertEqual(c.database.url, "https://wm-b.turso.io")
        self.assertIs(c.database, c.turso)
        self.assertNotIn("s3cret-token", repr(c))

    def test_one_setting_without_the_other_is_refused(self):
        for env in ({"TURSO_DATABASE_URL": "libsql://wm-b.turso.io"},
                    {"TURSO_AUTH_TOKEN": "t"}):
            with self.assertRaises(ValueError) as cm:
                Config.from_env(env)
            self.assertIn("TURSO_AUTH_TOKEN", str(cm.exception))

    def test_the_saved_file_is_used_only_when_asked_for(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "turso.json").write_text(json.dumps(
                {"url": "libsql://wm-b.turso.io", "token": "t"}))
            self.assertIsNone(Config.from_env({"WINGMATES_DATA_DIR": d}).turso)
            c = Config.from_env({"WINGMATES_DATA_DIR": d,
                                 "WINGMATES_USE_TURSO": "1"})
            self.assertEqual(c.turso.url, "https://wm-b.turso.io")

    def test_asking_for_the_file_when_it_is_missing_or_broken_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            for content in (None, "not json", '{"url": "libsql://x.turso.io"}'):
                if content is not None:
                    (Path(d) / "turso.json").write_text(content)
                with self.assertRaises(ValueError) as cm:
                    Config.from_env({"WINGMATES_DATA_DIR": d,
                                     "WINGMATES_USE_TURSO": "1"})
                self.assertIn("turso.json", str(cm.exception))
```

Add to `TestUsers` in `tests/test_users.py`:

```python
    def test_deleting_a_user_removes_their_rows_without_database_cascades(self):
        from contextlib import closing
        from fc.db import connect
        ann = self.users.create("Ann", "ann")["id"]
        bob = self.users.create("Bob", "bob")["id"]
        with closing(connect(self.users.database)) as db, db:
            db.execute("INSERT INTO flights (user_id, date, origin, dest,"
                       " distance_km, created_at) VALUES (?,?,?,?,?,?)",
                       (ann, "2024-03-09", "ATL", "LHR", 6760.0, "t"))
            db.execute("INSERT INTO flights (user_id, date, origin, dest,"
                       " distance_km, created_at) VALUES (?,?,?,?,?,?)",
                       (bob, "2024-03-09", "ATL", "JFK", 1200.0, "t"))
            db.execute("INSERT INTO mate_requests (from_id, to_id, status,"
                       " created_at) VALUES (?, ?, 'pending', 't')", (bob, ann))
            db.execute("INSERT INTO mates (user_lo, user_hi, created_at)"
                       " VALUES (?, ?, 't')", (min(ann, bob), max(ann, bob)))
        self.assertTrue(self.users.delete(ann))
        with closing(connect(self.users.database)) as db:
            counts = [db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("flights", "mate_requests", "mates", "users")]
        self.assertEqual(counts, [1, 0, 0, 1])
```

On a SQLite file this test passes today, because the file enforces foreign keys. Its Turso twin in `tests/test_on_turso.py` is the one that fails until `Users.delete` is explicit: the stand-in has foreign keys off.

- [ ] **Step 4: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -4`
Expected: many errors. `fc.db.connect` does not accept a `Turso` yet, and `Config` has no `turso`.

- [ ] **Step 5: Teach `fc/db.py` about Turso**

In `fc/db.py`, add to the imports:

```python
from .turso import Turso, TursoConnection
```

Replace `connect` with:

```python
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
```

Add above `init`:

```python
def _if_missing(ddl: str) -> str:
    return ddl.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)


def _init_turso(database: Turso) -> None:
    """Create the tables on Turso if they are not there. A Turso database
    starts empty, so there is nothing older to migrate from. One request."""
    connect(database).batch(
        [_if_missing(ddl).strip() for ddl in (_USERS, _FLIGHTS, _REQUESTS, _MATES)]
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
```

Change the signature of `init` to `def init(path) -> None:` and add as its first two lines:

```python
    if isinstance(path, Turso):
        return _init_turso(path)
```

- [ ] **Step 6: Delete a user's rows explicitly**

In `fc/users.py`, replace `delete` with:

```python
    def delete(self, user_id: int) -> bool:
        """Remove the user and everything that is theirs. Spelled out rather
        than left to ON DELETE CASCADE, which a hosted database may not
        enforce: an account deletion that left the flights behind would be a
        privacy failure nobody would see."""
        with closing(connect(self.database)) as db, db:
            db.execute("DELETE FROM flights WHERE user_id = ?", (user_id,))
            db.execute("DELETE FROM mate_requests WHERE from_id = ? OR to_id = ?",
                       (user_id, user_id))
            db.execute("DELETE FROM mates WHERE user_lo = ? OR user_hi = ?",
                       (user_id, user_id))
            return db.execute("DELETE FROM users WHERE id = ?",
                              (user_id,)).rowcount > 0
```

- [ ] **Step 7: Turso settings in `Config`**

In `fc/config.py`, add `from .turso import Turso` to the imports and `TURSO_FILE = "turso.json"` beside `GOOGLE_CLIENT_FILE`. Add above the `Config` class:

```python
def _turso(env: Mapping[str, str], data_dir: Path) -> Turso | None:
    """The Turso database to use, if any. Set by environment on a host. The
    saved file is for trying Turso from your own machine, and is used only
    when asked for, so its presence never switches a local app silently."""
    url, token = env.get("TURSO_DATABASE_URL"), env.get("TURSO_AUTH_TOKEN")
    if url or token:
        if not (url and token):
            raise ValueError(
                "TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must be set together")
        return Turso(url, token)
    if not _flag(env, "WINGMATES_USE_TURSO", False):
        return None
    path = data_dir / TURSO_FILE
    try:
        saved = json.loads(path.read_text())
        return Turso(saved["url"], saved["token"])
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError(
            f"WINGMATES_USE_TURSO=1 needs {path} with a url and a token; "
            "run tools/save_turso.py") from None
```

Add a field to `Config`, after `google_client_secret`:

```python
    turso: Turso | None = None
```

add a property after `db_path`:

```python
    @property
    def database(self):
        """Where the data lives: Turso when configured, else the local file."""
        return self.turso or self.db_path
```

and in `from_env` add `turso=_turso(env, data_dir),` to the `cls(...)` call.

`Turso`'s own `repr` already hides the token, so `repr(Config)` does too.

- [ ] **Step 8: Use `config.database` in the web layer**

In `fc/webapp.py`, change the two store constructions to:

```python
    history = History(airports, config.database)
    users = Users(config.database)
```

Replace the `healthz` route with:

```python
    @app.get("/healthz")
    def healthz():
        """Can the database be read? Asking never creates a missing file."""
        if not readable(config.database):
            return jsonify(ok=False), 503
        return jsonify(ok=True)
```

Add `from .db import readable` to the imports. The route was the only user of `sqlite3` and `closing` in this file: run `grep -n "sqlite3\.\|closing(" fc/webapp.py`, and if it prints nothing, remove the `import sqlite3` and `from contextlib import closing` lines.

- [ ] **Step 9: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -4`
Expected: `OK`. The count roughly doubles for the store and sign-in suites. Run it three times: the threading test must pass on both backends every time.

- [ ] **Step 10: Commit**

```bash
git add fc/db.py fc/users.py fc/history.py fc/mates.py fc/config.py fc/webapp.py tests/
git commit -m "Run the stores on a SQLite file or on Turso

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Batched CSV import with a cap

**Files:**
- Modify: `fc/history.py`, `tests/test_history.py`

On Turso every statement is a network request and a transaction has five seconds. Importing row by row would take one request per flight. The import now validates every row first, then sends the inserts in batches.

**Interfaces:**
- Consumes: `executemany` on either connection type.
- Produces: `fc.history.MAX_IMPORT_ROWS = 5000`. `UserHistory.import_csv` raises `ValueError` for a file with more data rows than that. Its return value is unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `TestImport` in `tests/test_history.py`, and add `MAX_IMPORT_ROWS` to the names imported from `fc.history`:

```python
    def test_a_file_over_the_cap_is_refused_and_adds_nothing(self):
        text = "date,from,to\n" + "2024-03-09,ATL,LHR\n" * (MAX_IMPORT_ROWS + 1)
        with self.assertRaises(ValueError) as cm:
            self.h.import_csv(text)
        self.assertIn("5,000", str(cm.exception))
        self.assertEqual(self.h.list(), [])

    def test_a_file_at_the_cap_is_accepted(self):
        days = [f"20{y:02d}-{m:02d}-{d:02d}" for y in range(10, 24)
                for m in range(1, 13) for d in range(1, 29)]
        self.assertGreaterEqual(len(days), MAX_IMPORT_ROWS - 300)
        text = "date,from,to\n" + "".join(f"{day},ATL,LHR\n" for day in days)
        self.assertEqual(self.h.import_csv(text)["added"], len(days))

    def test_blank_lines_do_not_count_towards_the_cap(self):
        text = "date,from,to\n" + "\n" * (MAX_IMPORT_ROWS + 50) + "2024-03-09,ATL,LHR\n"
        self.assertEqual(self.h.import_csv(text)["added"], 1)
```

Add to `tests/test_on_turso.py`, above the `if __name__` line:

```python
class TestImportIsBatchedOnTurso(test_history.HistoryCase):
    on_turso = True

    def test_a_large_import_takes_a_handful_of_requests(self):
        days = [f"2024-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 29)]
        text = "date,from,to\n" + "".join(f"{day},ATL,LHR\n" for day in days)
        self.fake.calls.clear()
        self.assertEqual(self.h.import_csv(text)["added"], len(days))   # 336 rows
        # One read for existing flights, two batches of inserts, one commit.
        self.assertLessEqual(len(self.fake.calls), 5)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_history tests.test_on_turso 2>&1 | grep -E "^(ERROR|FAIL)|^Ran|^FAILED"`
Expected: `ImportError` for `MAX_IMPORT_ROWS`.

- [ ] **Step 3: Implement**

In `fc/history.py`, add below `TEMPLATE_COLUMNS`:

```python
# A lifetime of flights is a few thousand rows. The cap keeps an import inside
# the few seconds a hosted database allows one transaction.
MAX_IMPORT_ROWS = 5000

_INSERT = ("INSERT INTO flights (user_id, date, origin, dest, airline,"
           " flight_number, aircraft, seat, notes, distance_km, created_at)"
           " VALUES (?,?,?,?,?,?,?,?,?,?,?)")
```

In `UserHistory`, replace `_insert` and `add` with:

```python
    def _values(self, d, o, t, extra: dict) -> tuple:
        """The row to insert for one flight, in _INSERT's column order."""
        return (self.user_id, d.isoformat(), o.iata, t.iata,
                *[(extra.get(k) or "").strip() for k in OPTIONAL],
                great_circle_km(o.lat, o.lon, t.lat, t.lon),
                datetime.now(UTC).isoformat())

    def add(self, day: str, origin: str, dest: str, **extra) -> dict:
        d, o, t = self._validate(day, origin, dest)
        with closing(connect(self.database)) as db, db:
            fid = db.execute(_INSERT, self._values(d, o, t, extra)).lastrowid
        return self.get(fid)
```

Replace the body of `import_csv` from the line `added = skipped = 0` to its `return` with:

```python
        rows = [(line, raw) for line, raw in enumerate(reader, start=2)
                if any(c.strip() for c in raw)]
        if len(rows) > MAX_IMPORT_ROWS:
            raise ValueError(
                f"a file can hold at most {MAX_IMPORT_ROWS:,} flights; this one "
                f"has {len(rows):,}. Split it and import the parts.")

        skipped = 0
        errors: list[dict] = []
        inserts: list[tuple] = []
        with closing(connect(self.database)) as db, db:
            seen = {(r["date"], r["origin"], r["dest"], r["flight_number"].upper())
                    for r in db.execute(
                        "SELECT * FROM flights WHERE user_id = ?",
                        (self.user_id,))}
            # Check every row first, then insert the good ones together: on a
            # hosted database each statement is a network request.
            for line, raw in rows:
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
                inserts.append(self._values(d, o, t, row))
            if inserts:
                db.executemany(_INSERT, inserts)
        return {"added": len(inserts), "skipped": skipped, "errors": errors}
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add fc/history.py tests/test_history.py tests/test_on_turso.py
git commit -m "Import CSV in batches, capped at 5,000 flights

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Hosted rules for a host with no disk

**Files:**
- Modify: `fc/hosted.py`, `fc/config.py`, `tests/test_signin.py`, `tests/test_config.py`, `tests/test_webapp.py`

**Interfaces:**
- Consumes: `Config.turso`, `Config.secret_key`, `fc.db.readable`.
- Produces:
  - `fc.hosted.build` raises `RuntimeError` when Turso is configured and `SECRET_KEY` is not set.
  - `Config.from_env` base URL order: `WINGMATES_BASE_URL`, then `https://` + `RENDER_EXTERNAL_HOSTNAME`, then `https://` + `VERCEL_PROJECT_PRODUCTION_URL`, then the localhost default.

- [ ] **Step 1: Write the failing tests**

Add to `TestHosted` in `tests/test_signin.py`:

```python
    def turso_env(self, **over):
        return {"WINGMATES_AUTH": "google", "GOOGLE_CLIENT_ID": "id",
                "GOOGLE_CLIENT_SECRET": "secret", "SECRET_KEY": "a-fixed-key",
                "TURSO_DATABASE_URL": "libsql://wm-test.turso.io",
                "TURSO_AUTH_TOKEN": "test-token",
                "WINGMATES_DATA_DIR": str(self.dir / "must-not-be-created"),
                "WINGMATES_BASE_URL": BASE, **over}

    def with_fake_turso(self):
        from unittest import mock
        from tests.fake_turso import FakeTurso
        fake = FakeTurso(self.dir / "remote.db")
        patcher = mock.patch("fc.turso.send", fake.send)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def test_on_turso_it_refuses_to_start_without_a_secret_key(self):
        self.with_fake_turso()
        env = self.turso_env()
        del env["SECRET_KEY"]
        with self.assertRaises(RuntimeError) as cm:
            build(env, sign_in=self.google)
        self.assertIn("SECRET_KEY", str(cm.exception))

    def test_on_turso_it_runs_without_writing_any_file(self):
        fake = self.with_fake_turso()
        app = build(self.turso_env(), sign_in=self.google)
        client = app.test_client()
        client.set_cookie("session", self.signed_in_cookie(app))
        client.post("/api/username", json={"username": "brett"}, headers=ORIGIN)
        client.post("/api/history", headers=ORIGIN,
                    json={"date": "2024-03-09", "from": "ATL", "to": "LHR"})
        self.assertEqual(len(client.get("/api/history").get_json()["flights"]), 1)
        self.assertEqual(client.get("/healthz").get_json(), {"ok": True})
        self.assertGreater(len(fake.calls), 0)
        self.assertFalse((self.dir / "must-not-be-created").exists())
        self.assertFalse((self.dir / "flights.db").exists())

    def test_on_turso_an_unreachable_database_fails_the_health_check(self):
        import sqlite3
        from unittest import mock
        self.with_fake_turso()
        client = build(self.turso_env(), sign_in=self.google).test_client()
        with mock.patch("fc.turso.send",
                        side_effect=sqlite3.OperationalError("database unreachable")):
            r = client.get("/healthz")
        self.assertEqual((r.status_code, r.get_json()), (503, {"ok": False}))
```

Add to `TestBaseUrl` in `tests/test_config.py`:

```python
    def test_on_vercel_it_defaults_to_the_production_address(self):
        vercel = {"VERCEL_PROJECT_PRODUCTION_URL": "wingmates.vercel.app"}
        self.assertEqual(Config.from_env(vercel).base_url,
                         "https://wingmates.vercel.app")
        both = {**vercel, "WINGMATES_BASE_URL": "https://wingmates.example"}
        self.assertEqual(Config.from_env(both).base_url,
                         "https://wingmates.example")
```

Add to `TestHealth` in `tests/test_webapp.py`:

```python
    def test_a_data_folder_with_awkward_characters_still_reports_healthy(self):
        odd = self.dir / "q?mark #1 100%"
        odd.mkdir()
        app = create_app(Config(data_dir=odd, live=False), airports=self.airports)
        self.assertEqual(app.test_client().get("/healthz").get_json(), {"ok": True})
        self.assertEqual(sorted(p.name for p in odd.iterdir()), ["flights.db"])
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_signin.TestHosted tests.test_config.TestBaseUrl tests.test_webapp.TestHealth 2>&1 | grep -E "^(ERROR|FAIL)|^Ran|^FAILED"`
Expected: the secret-key test and the Vercel address test fail. The others may already pass after Task 2; that is fine, they pin behaviour this task must not break.

- [ ] **Step 3: Implement**

In `fc/hosted.py`, add after the `auth` check in `build`:

```python
    if config.turso is not None and not config.secret_key:
        raise RuntimeError(
            "with a Turso database, SECRET_KEY must be set: a host without a "
            "disk has nowhere to keep a generated session key")
```

In `fc/config.py`, replace the last two lines of `_base_url` with:

```python
    for name in ("RENDER_EXTERNAL_HOSTNAME", "VERCEL_PROJECT_PRODUCTION_URL"):
        host = env.get(name)
        if host:
            return f"https://{host}"
    return DEFAULT_BASE_URL
```

and update its docstring's second sentence to: `On Render and on Vercel the service's own hostname is known, so nothing needs setting until a custom domain is added.`

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add fc/hosted.py fc/config.py tests/test_signin.py tests/test_config.py tests/test_webapp.py
git commit -m "Require a session key on a host without a disk; know Vercel's address

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Vercel layout

**Files:**
- Create: `wsgi.py` (repository root), `.python-version`, `public/static/` (by moving files)
- Modify: `fc/webapp.py`, `Dockerfile`, `README.md`

Vercel serves anything under `public/` straight from its network and says Flask's own static folder should not be used. The `.js` and `.css` files move there. The HTML pages do not: `/` must go through the app, which decides whether to show the app, the sign-in page or the username page.

**Interfaces:**
- Consumes: `fc.hosted.build`.
- Produces: `wsgi:app` at the repository root. `/static/<file>` URLs are unchanged.

- [ ] **Step 1: Move the assets**

```bash
mkdir -p public/static
git mv web/app.js web/history.js web/social.js web/globe.js web/style.css public/static/
ls web public/static
```

Expected: `web` holds `index.html`, `login.html`, `welcome.html`; `public/static` holds the five moved files.

- [ ] **Step 2: Point Flask at the new folder**

In `fc/webapp.py`, replace the `WEB_DIR = ...` line with:

```python
ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"                       # HTML pages, served by routes
STATIC_DIR = ROOT / "public" / "static"      # .js and .css, served at /static/
```

and in `create_app` change `static_folder=str(WEB_DIR)` to `static_folder=str(STATIC_DIR)`.

Run: `.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -3`
Expected: `OK`. The existing tests fetch `/static/style.css` and `/`, so they cover both folders.

- [ ] **Step 3: Add the Vercel entry point**

Create `wsgi.py` in the repository root:

```python
"""The entry point Vercel looks for: a Flask app named `app` in wsgi.py.

Builds the hosted app, which insists on sign-in. To run Wingmates on your own
machine use run.py instead.
"""
from fc.hosted import build

app = build()
```

Create `.python-version`:

```
3.13
```

- [ ] **Step 4: Keep the container working**

In `Dockerfile`, add a line after `COPY web ./web`:

```dockerfile
COPY public ./public
```

- [ ] **Step 5: Check the entry point runs as Vercel would run it**

```bash
D=$(mktemp -d)
WINGMATES_AUTH=google GOOGLE_CLIENT_ID=x GOOGLE_CLIENT_SECRET=y SECRET_KEY=k \
  WINGMATES_DATA_DIR=$D WINGMATES_BASE_URL=http://localhost:10002 \
  .venv/bin/gunicorn --workers 1 --bind 127.0.0.1:10002 wsgi:app &
sleep 2
curl -s http://localhost:10002/healthz; echo
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://localhost:10002/
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:10002/static/app.js
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:10002/login
kill %1
```

Expected: `{"ok":true}`, `302 http://localhost:10002/login`, `200`, `200`.

Then start the `wingmates-dev` launch configuration, open `http://localhost:8817`, and confirm the page loads with its styles, the globe renders, and there are no console errors. This checks the moved files in a real browser.

- [ ] **Step 6: Update the README layout**

In `README.md`, in the Layout block, replace the four lines beginning `web/index.html`, `web/app.js`, `web/history.js`, `web/globe.js` and the `web/social.js` and `web/login.html, welcome.html` lines with:

```
web/                    HTML pages: the app, sign-in, choose-a-username
public/static/app.js    live tracker UI and the flat map (Leaflet)
public/static/history.js   My flights UI: form, list, edit, route drawing
public/static/social.js    Social tab
public/static/globe.js  3D globe (three.js), loaded as an ES module
public/static/style.css styles
wsgi.py                 entry point for Vercel
fc/turso.py             Turso client: SQL over HTTP, shaped like sqlite3
```

- [ ] **Step 7: Commit**

```bash
git add -A wsgi.py .python-version public web fc/webapp.py Dockerfile README.md
git commit -m "Lay the project out for Vercel

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Tools and the deploy guide

**Files:**
- Create: `tools/save_turso.py`, `tools/turso_check.py`, `docs/deploy-vercel.md`
- Modify: `README.md`, `docs/deploy-render.md`

**Interfaces:**
- Consumes: `Turso`, `fc.db.init`, `Users`, `History`, `Airports`.
- Produces: `tools/save_turso.py` writes `~/.wingmates/turso.json` (mode 600) from prompted input. `tools/turso_check.py` exercises a real Turso database and exits 0 on success.

- [ ] **Step 1: A way to save the Turso settings without pasting them into a chat**

Create `tools/save_turso.py`:

```python
#!/usr/bin/env python3
"""Save your Turso database address and token to ~/.wingmates/turso.json.

The token is typed at a hidden prompt, so it is not shown on screen, kept in
your shell history, or pasted anywhere else.

    .venv/bin/python tools/save_turso.py
"""
import getpass
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.turso import Turso


def main() -> int:
    url = input("Turso database URL (starts with libsql://): ").strip()
    token = getpass.getpass("Turso auth token (hidden): ").strip()
    try:
        Turso(url, token)
    except ValueError as e:
        print(f"Not saved: {e}")
        return 1
    folder = Path.home() / ".wingmates"
    folder.mkdir(mode=0o700, exist_ok=True)
    path = folder / "turso.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"url": url, "token": token}, f)
    os.chmod(path, 0o600)
    print(f"Saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: A check against a real Turso database**

Create `tools/turso_check.py`:

```python
#!/usr/bin/env python3
"""Check that Wingmates works against your real Turso database.

Reads ~/.wingmates/turso.json (see tools/save_turso.py), creates the tables if
they are missing, then creates a throwaway user, adds and reads back a flight,
deletes the user and confirms nothing of theirs is left. Prints each step. The
token is never printed.

    .venv/bin/python tools/turso_check.py
"""
import secrets
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.airports import Airports
from fc.config import Config
from fc.db import connect, readable
from fc.history import History
from fc.users import Users


def main() -> int:
    try:
        config = Config.from_env({"WINGMATES_USE_TURSO": "1"})
    except ValueError as e:
        print(f"Cannot start: {e}")
        return 1
    database = config.turso
    print(f"database  {database.url}")

    try:
        t0 = time.perf_counter()
        history = History(Airports(), database)
        users = Users(database)
        print(f"tables    ready ({time.perf_counter() - t0:.2f}s)")
        if not readable(database):
            print("FAILED    the users table cannot be read")
            return 1

        name = "check_" + secrets.token_hex(4)
        user = users.create("Turso check", name)
        mine = history.for_user(user["id"])
        print(f"user      created @{name}")

        t0 = time.perf_counter()
        flight = mine.add("2024-03-09", "ATL", "LHR", notes="turso check")
        listed = mine.list()
        print(f"flight    added and read back, {flight['distance_mi']} mi "
              f"({time.perf_counter() - t0:.2f}s)")
        if [f["id"] for f in listed] != [flight["id"]]:
            print("FAILED    the flight did not read back")
            return 1

        try:
            users.create("Dup", name)
            print("FAILED    a duplicate username was accepted")
            return 1
        except ValueError:
            print("unique    a duplicate username is refused")

        users.delete(user["id"])
        with closing(connect(database)) as db:
            left = db.execute("SELECT COUNT(*) FROM flights WHERE user_id = ?",
                              (user["id"],)).fetchone()[0]
        if users.get(user["id"]) is not None or left:
            print("FAILED    the throwaway user or their flight was left behind")
            return 1
        print("cleanup   throwaway user and flight removed")
    except sqlite3.Error as e:
        print(f"FAILED    {type(e).__name__}: {e}")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run: `.venv/bin/python -c "import ast; [ast.parse(open(f).read()) for f in ('tools/save_turso.py', 'tools/turso_check.py')]; print('ok')"`
Expected: `ok`. These two scripts are run for real in Task 7, once there is a Turso database.

- [ ] **Step 3: Write the deploy guide**

Create `docs/deploy-vercel.md`:

```markdown
# Deploying Wingmates for free: Vercel + Turso

The app runs on Vercel's free Hobby plan and keeps its data in a free Turso
database. Neither needs a payment card. Vercel's Hobby plan is for personal,
non-commercial use; if a usage limit is exceeded the site is paused, not
billed.

For a paid alternative with faster pages and week-long backups, see
[deploy-render.md](deploy-render.md).

## Before you start

- Google sign-in is set up: see [google-sign-in-setup.md](google-sign-in-setup.md).
- The code is pushed to the `main` branch on GitHub.

## 1. Create the database

1. Sign up at https://turso.tech.
2. Create a database named `wingmates`.
3. Copy its URL (it starts with `libsql://`) and create a token for it.
4. Save both on your own machine and check they work:

       .venv/bin/python tools/save_turso.py
       .venv/bin/python tools/turso_check.py

   The check creates a throwaway user and flight, reads them back and removes
   them. It should end with `OK`.

## 2. Create the Vercel project

1. Sign up at https://vercel.com with your GitHub account.
2. Choose **Add New**, **Project**, and import the `wingmates` repository.
3. Before deploying, open **Environment Variables** and add:

   | Name | Value |
   |---|---|
   | `WINGMATES_AUTH` | `google` |
   | `SECRET_KEY` | a long random string; `python3 -c "import secrets; print(secrets.token_hex(32))"` makes one |
   | `GOOGLE_CLIENT_ID` | `client_id` from `~/.wingmates/google-client.json` |
   | `GOOGLE_CLIENT_SECRET` | `client_secret` from the same file |
   | `TURSO_DATABASE_URL` | the `libsql://` URL |
   | `TURSO_AUTH_TOKEN` | the Turso token |

4. Deploy.

## 3. Tell Google the new address

Vercel shows the project's address, like `https://wingmates.vercel.app`.

1. In the Google Cloud console open **Google Auth Platform**, **Clients**, your
   client.
2. Under **Authorized redirect URIs** add `https://YOUR-ADDRESS/auth/callback`.
3. Save.

## 4. Sign in and invite people

Open the address, press **Continue with Google**, and choose a username.

**Google's test users list is your invite list.** While the Google app's
publishing status is **Testing**, only people on that list can sign in.
Wingmates has no invite system of its own.

## Updating

Every push to `main` deploys automatically. Vercel also builds a preview for
other branches at a different address; previews answer "unknown host", because
the app only answers at its real address.

## Limits and backups

- A CSV import holds at most 5,000 flights.
- Pages are slower than on your own machine: every database query is a network
  request. The first visit after a quiet spell is slower still.
- Turso's free plan keeps one day of point-in-time restore. Each person can
  export their own flights as CSV.
- The database tables are created on first start. A later change to their
  shape will need a migration step that does not exist yet.

## If something is wrong

- **Every page says "unknown host".** Set `WINGMATES_BASE_URL` to the site's
  address, including `https://`, and redeploy.
- **The deployment fails at start.** Open the function logs. The message names
  the missing setting: `WINGMATES_AUTH`, `SECRET_KEY`, the Google client, or
  the Turso pair.
- **Sign-in works but nothing saves.** Run `tools/turso_check.py` locally; it
  reports whether Turso is reachable with the saved token.
- **Google shows `redirect_uri_mismatch`.** The redirect URI in the Google
  console does not exactly match `https://YOUR-ADDRESS/auth/callback`.
```

- [ ] **Step 4: README and cross-links**

In `README.md`, replace the sentence that begins `To put it on the internet for friends, see` with:

```markdown
To put it on the internet for friends, free, see
[docs/deploy-vercel.md](docs/deploy-vercel.md). A paid alternative is in
[docs/deploy-render.md](docs/deploy-render.md).
```

Add these rows to the Settings table:

```markdown
| `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` | unset | Keep the data in a Turso database instead of the local file. `SECRET_KEY` is then required. |
| `WINGMATES_USE_TURSO` | `0` | `1` uses the Turso settings saved in `~/.wingmates/turso.json`, for trying Turso from your own machine. |
```

At the top of `docs/deploy-render.md`, directly under its title, add:

```markdown
This is the paid route. For a free one, see [deploy-vercel.md](deploy-vercel.md).
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add tools docs/deploy-vercel.md docs/deploy-render.md README.md
git commit -m "Add Turso tools and the Vercel deploy guide

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Prove it against the real services, then go live

The stand-in server reflects a reading of Turso's documentation. This task is where the client meets the real service. It needs the owner at each step: their Turso account, their Vercel account and their Google account.

- [ ] **Step 1: Ask the owner to create the Turso database**

Section 1 of `docs/deploy-vercel.md`, up to and including `tools/save_turso.py`. The owner runs that script themselves so the token is typed at a hidden prompt.

- [ ] **Step 2: Run the real check**

Run: `.venv/bin/python tools/turso_check.py`
Expected: lines for `database`, `tables`, `user`, `flight`, `unique`, `cleanup`, then `OK`.

If it fails, the failure is in `fc/turso.py`'s reading of the API. Use superpowers:systematic-debugging: capture the real response shape, fix the client, and add the real shape to `tests/test_turso.py` and `tests/fake_turso.py` so the stand-in matches the service. Do not continue until this prints `OK`.

- [ ] **Step 3: Run the whole app locally against Turso**

```bash
WINGMATES_AUTH=google WINGMATES_USE_TURSO=1 .venv/bin/python run.py --no-browser
```

Ask the owner to open `http://localhost:8817`, sign in, choose a username, add a flight, open the Social tab, sign out and sign in again. This account lives in Turso and will still be there on Vercel. Note how long pages take.

- [ ] **Step 4: Merge and push**

After the branch review, and with the owner's approval, fast-forward `main` and push.

- [ ] **Step 5: Ask the owner to create the Vercel project**

Sections 2 and 3 of `docs/deploy-vercel.md`. Ask them to report the address and whether the deployment succeeded; if not, the build or function log.

- [ ] **Step 6: Check the live site from outside**

```bash
A=https://THEIR-ADDRESS
curl -s $A/healthz; echo
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" $A/
curl -s $A/api/me; echo
curl -s -o /dev/null -w "%{http_code}\n" $A/static/app.js
curl -sI $A/auth/login | grep -i "^location:" | grep -c "accounts.google.com"
```

Expected: `{"ok":true}`, `302 https://THEIR-ADDRESS/login`, `{"error":"sign in required"}`, `200`, `1`.

If `/api/me` answers 403 "unknown host", Vercel is presenting a host name the app does not expect: ask the owner to set `WINGMATES_BASE_URL` to the address and redeploy.

- [ ] **Step 7: Ask the owner to confirm the real thing**

1. They can sign in on the live site and their username and flight from Step 3 are there.
2. A friend, added as a Google test user, can sign in from their own device.
3. The two can find each other by username, become mates, and see each other's wingspans and routes.
4. After a push to `main`, the site redeploys and both are still signed in with their flights intact.
