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
