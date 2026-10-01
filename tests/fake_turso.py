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
