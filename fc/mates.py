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
        self.database = history.database

    # ----------------------------------------------------------------- lookup
    def card(self, viewer_id: int, username: str) -> dict | None:
        """What anyone may see of the person with exactly this username."""
        person = self.users.by_username(username)
        if person is None:
            return None
        with closing(connect(self.database)) as db:
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
        with closing(connect(self.database)) as db, db:
            if _are_mates(db, from_id, to_id):
                raise ValueError("you are already mates")
            mine, theirs = _status(db, from_id, to_id), _status(db, to_id, from_id)
            if theirs in _SHOWN:
                # They asked first (even if it was declined): adding them back
                # is the answer to their request.
                _join(db, from_id, to_id)
            elif mine in _SHOWN:
                pass
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
                if mine == "withdrawn":
                    # Still blocked, but it must look to the sender exactly
                    # like a fresh request: same cap, same place in the list.
                    db.execute(
                        "UPDATE mate_requests SET status = 'declined',"
                        " created_at = ? WHERE from_id = ? AND to_id = ?",
                        (_now(), from_id, to_id))
                else:
                    db.execute(
                        "INSERT INTO mate_requests (from_id, to_id, status,"
                        " created_at) VALUES (?, ?, 'pending', ?)",
                        (from_id, to_id, _now()))
            relation = _relation(db, from_id, to_id)
        return {**{k: target[k] for k in PERSON_FIELDS}, "relation": relation}

    def accept(self, user_id: int, other_id: int) -> bool:
        with closing(connect(self.database)) as db, db:
            if _status(db, other_id, user_id) != "pending":
                return False
            _join(db, user_id, other_id)
            return True

    def decline(self, user_id: int, other_id: int) -> bool:
        with closing(connect(self.database)) as db, db:
            return db.execute(
                "UPDATE mate_requests SET status = 'declined'"
                " WHERE from_id = ? AND to_id = ? AND status = 'pending'",
                (other_id, user_id)).rowcount > 0

    def cancel(self, user_id: int, other_id: int) -> bool:
        with closing(connect(self.database)) as db, db:
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
        with closing(connect(self.database)) as db, db:
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
        with closing(connect(self.database)) as db:
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
        with closing(connect(self.database)) as db:
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
