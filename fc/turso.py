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
CHUNK = 500                     # statements per request in executemany()
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
    try:
        return reply.json()
    except ValueError:
        raise sqlite3.OperationalError(
            "database sent a reply that is not JSON") from None


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
    if (str(err.get("code", "")).startswith("SQLITE_CONSTRAINT")
            or "constraint failed" in message):
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

    def _lost(self, why: str) -> sqlite3.OperationalError:
        """Forget the far side and report why. After this the connection has
        no transaction: nothing more is sent as if one were still open."""
        self._baton, self._tx = None, False
        return sqlite3.OperationalError(why)

    def _run(self, statements, close: bool) -> list:
        """Send statements in one request. Returns one item per statement: a
        result dict, or the exception that statement produced. Errors come
        back as values so the caller can update its state before raising.

        The reply is checked, not trusted. A transaction that lost its
        connection, or a reply missing results, must stop everything here:
        carrying on would send the remaining writes on a fresh connection,
        where each would commit on its own."""
        if self._tx and not self._baton:
            raise self._lost("the transaction's connection was lost")
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
        results = reply.get("results") if isinstance(reply, dict) else None
        if not isinstance(results, list) or len(results) < len(reqs):
            raise self._lost("database sent an incomplete reply")
        baton = None if close else reply.get("baton")
        if not close and not baton:
            raise self._lost("database closed the connection mid-transaction")
        self._baton = baton
        base_url = reply.get("base_url")
        if isinstance(base_url, str) and base_url.startswith("https://"):
            self._base_url = base_url        # the token is only sent over https
        out = []
        try:
            for item in results[:len(statements)]:
                out.append(_error(item.get("error") or {})
                           if item["type"] == "error"
                           else item["response"]["result"])
        except (KeyError, TypeError, AttributeError):
            raise self._lost("database sent a reply in an unexpected shape") from None
        return out

    @staticmethod
    def _first_error(results):
        for r in results:
            if isinstance(r, Exception):
                raise r

    def _begin(self) -> None:
        """Open a transaction, alone in its own request. Sending BEGIN in the
        same request as the first write would save a round trip, but if BEGIN
        failed the write would still run, outside any transaction."""
        (begin,) = self._run([("BEGIN", ())], close=False)
        if isinstance(begin, Exception):
            try:
                self._run([], close=True)        # release the connection
            except sqlite3.Error:
                pass
            self._baton = None
            raise begin
        self._tx = True

    def execute(self, sql: str, params=()) -> Result:
        words = sql.split(None, 1)
        if not words:
            raise sqlite3.OperationalError("empty statement")
        verb = words[0].upper()
        if verb == "BEGIN":
            if not self._tx:
                self._begin()
            return Result({})
        if verb in _WRITES and not self._tx:
            self._begin()
        (result,) = self._run([(sql, tuple(params))], close=not self._tx)
        if isinstance(result, Exception):
            raise result
        return Result(result)

    def executemany(self, sql: str, rows) -> None:
        """Run one statement for many rows, a chunk per request, all inside
        the connection's transaction."""
        rows = [tuple(r) for r in rows]
        if not rows:
            return
        if not self._tx:
            self._begin()
        for start in range(0, len(rows), CHUNK):
            self._first_error(self._run(
                [(sql, r) for r in rows[start:start + CHUNK]], close=False))

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
