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
        self.addCleanup(self.fake.shutdown)
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
        rows = [(f"n{i}",) for i in range(1100)]
        with self.conn() as c, c:
            c.executemany("INSERT INTO t (name) VALUES (?)", rows)
        # BEGIN, then 500 + 500 + 100, then the commit: five requests.
        self.assertEqual(len(self.fake.calls), 5)
        self.assertEqual(len(self.names()), 1100)

    def test_executemany_with_no_rows_sends_nothing(self):
        with self.conn() as c, c:
            c.executemany("INSERT INTO t (name) VALUES (?)", [])
        self.assertEqual(self.fake.calls, [])

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


class TestRepliesAreNotTrusted(TursoCase):
    """A transaction must never quietly turn into separate auto-commits. Each
    of these replies is one a real service could send and the stand-in, left
    alone, never would."""

    INSERT = "INSERT INTO t (name) VALUES (?)"

    def test_a_stream_dropped_at_begin_writes_nothing(self):
        self.fake.drop_stream_on_reply = 1
        with self.assertRaises(sqlite3.OperationalError):
            with self.conn() as c, c:
                c.execute(self.INSERT, ("a",))
        self.assertNotIn(self.INSERT, self.fake.statements())
        self.assertEqual(self.names(), [])

    def test_a_stream_dropped_mid_transaction_stops_everything(self):
        self.fake.drop_stream_on_reply = 2
        with self.assertRaises(sqlite3.OperationalError):
            with self.conn() as c, c:
                c.execute(self.INSERT, ("a",))
                c.execute(self.INSERT, ("b",))
        # The second write must not have gone out on a fresh, auto-committing
        # connection.
        self.assertEqual(self.fake.statements().count(self.INSERT), 1)
        self.assertEqual(self.names(), [])

    def test_a_failed_begin_sends_no_write(self):
        self.fake.fail_begin = True
        with self.assertRaises(sqlite3.OperationalError):
            with self.conn() as c, c:
                c.execute(self.INSERT, ("a",))
        with self.assertRaises(sqlite3.OperationalError):
            with self.conn() as c, c:
                c.executemany(self.INSERT, [("a",), ("b",)])
        self.assertNotIn(self.INSERT, self.fake.statements())
        self.fake.fail_begin = False
        self.assertEqual(self.names(), [])

    def test_a_reply_with_too_few_results_is_an_error_not_a_success(self):
        self.fake.truncate_results = True
        with self.assertRaises(sqlite3.OperationalError):
            with self.conn() as c, c:
                c.executemany(self.INSERT, [("a",), ("b",), ("a",)])
        with self.assertRaises(sqlite3.OperationalError):
            with self.conn() as c:
                c.execute("SELECT COUNT(*) FROM t")
        self.fake.truncate_results = False
        self.assertEqual(self.names(), [])

    def test_an_empty_statement_is_an_error_not_a_crash(self):
        with self.conn() as c:
            with self.assertRaises(sqlite3.OperationalError):
                c.execute("   ")

    def test_a_constraint_error_is_recognised_by_message_too(self):
        for err in ({"message": "UNIQUE constraint failed: users.username",
                     "code": "SOMETHING_ELSE"},
                    {"message": "SQLite error: UNIQUE constraint failed: t.name"},
                    {"message": "x", "code": "SQLITE_CONSTRAINT_UNIQUE"}):
            self.assertIsInstance(turso._error(err), sqlite3.IntegrityError, err)
        self.assertNotIsInstance(turso._error({"message": "no such table: t"}),
                                 sqlite3.IntegrityError)


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

    def test_an_unreadable_or_misshapen_reply_is_an_operational_error(self):
        unreadable = self.reply()
        unreadable.json.side_effect = ValueError("not json")
        for reply in (unreadable, self.reply(body=["a", "list"]),
                      self.reply(body={"baton": None}),
                      self.reply(body={"results": [{"type": "ok"}]})):
            with mock.patch.object(turso._session, "post", return_value=reply):
                with self.assertRaises(sqlite3.OperationalError):
                    TursoConnection(self.db).execute("SELECT 1")

    def test_a_base_url_that_is_not_https_is_not_followed(self):
        first = self.reply(body={"baton": "b1", "base_url": "http://evil.example",
                                 "results": [{"type": "ok", "response": {
                                     "type": "execute", "result": {}}}]})
        with mock.patch.object(turso._session, "post",
                               return_value=first) as post:
            conn = TursoConnection(self.db)
            conn.execute("BEGIN")
            conn.execute("SELECT 1")
        self.assertTrue(all(call[0][0].startswith("https://wm-test.turso.io")
                            for call in post.call_args_list))

    def test_a_connection_survives_nothing_after_a_transport_failure(self):
        conn = TursoConnection(self.db)
        with mock.patch.object(turso._session, "post",
                               side_effect=requests.ConnectionError()):
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("INSERT INTO t (name) VALUES (?)", ("a",))
            conn.close()                         # must not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
