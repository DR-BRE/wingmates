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


if __name__ == "__main__":
    unittest.main(verbosity=2)
