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

    user = None
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

        # A transaction that fails part-way must keep nothing.
        twin = "check_" + secrets.token_hex(4)
        try:
            with closing(connect(database)) as db, db:
                for _ in range(2):
                    db.execute("INSERT INTO users (username, name, created_at)"
                               " VALUES (?, 'x', 't')", (twin,))
            print("FAILED    a duplicate inside a transaction was accepted")
            return 1
        except sqlite3.IntegrityError:
            pass
        if users.by_username(twin) is not None:
            print("FAILED    a failed transaction kept its first row")
            users.delete(users.by_username(twin)["id"])
            return 1
        print("rollback  a failed transaction keeps nothing")

        # A year of daily flights in one file: how long does an import take?
        days = [f"2023-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 29)]
        text = "date,from,to\n" + "".join(f"{day},ATL,JFK\n" for day in days)
        t0 = time.perf_counter()
        report = mine.import_csv(text)
        took = time.perf_counter() - t0
        if report["added"] != len(days) or report["errors"]:
            print(f"FAILED    import added {report['added']} of {len(days)}")
            return 1
        print(f"import    {len(days)} flights in {took:.2f}s")
    except sqlite3.Error as e:
        print(f"FAILED    {type(e).__name__}: {e}")
        return 1
    finally:
        # Leave nothing behind, whatever happened above.
        if user is not None:
            try:
                users.delete(user["id"])
                with closing(connect(database)) as db:
                    left = db.execute(
                        "SELECT COUNT(*) FROM flights WHERE user_id = ?",
                        (user["id"],)).fetchone()[0]
                if users.get(user["id"]) is not None or left:
                    print("WARNING   the throwaway user or flights were left behind")
                else:
                    print("cleanup   throwaway user and flights removed")
            except sqlite3.Error as e:
                print(f"WARNING   cleanup failed: {type(e).__name__}")

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
