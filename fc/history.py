"""Flight history: the flights a person has taken, entered by hand or by CSV.

Separate from the live tracker on purpose. The tracker knows where an aircraft
is; this knows where a person went. A history flight is two airports and a
date — none of it comes from ADS-B.
"""
from __future__ import annotations

import csv
import io
import math
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

from .airports import Airports

DB_FILE = Path.home() / ".wingmates" / "flights.db"
KM_PER_MILE = 1.609344
EARTH_RADIUS_KM = 6371.0088

OPTIONAL = ("airline", "flight_number", "aircraft", "seat", "notes")
TEMPLATE_COLUMNS = ("date", "from", "to") + OPTIONAL

# Header spellings accepted on import, so a spreadsheet someone already keeps
# usually works without renaming columns.
_ALIASES = {
    "date": "date", "departure date": "date", "flight date": "date",
    "from": "from", "origin": "from", "departure": "from", "dep": "from",
    "to": "to", "destination": "to", "arrival": "to", "dest": "to", "arr": "to",
    "airline": "airline", "carrier": "airline",
    "flight_number": "flight_number", "flight number": "flight_number",
    "flight": "flight_number", "flight no": "flight_number",
    "aircraft": "aircraft", "aircraft type": "aircraft", "plane": "aircraft",
    "seat": "seat",
    "notes": "notes", "note": "notes", "comment": "notes",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS flights (
    id            INTEGER PRIMARY KEY,
    date          TEXT NOT NULL,
    origin        TEXT NOT NULL,
    dest          TEXT NOT NULL,
    airline       TEXT NOT NULL DEFAULT '',
    flight_number TEXT NOT NULL DEFAULT '',
    aircraft      TEXT NOT NULL DEFAULT '',
    seat          TEXT NOT NULL DEFAULT '',
    notes         TEXT NOT NULL DEFAULT '',
    distance_km   REAL NOT NULL,
    created_at    TEXT NOT NULL
)"""


def great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class History:
    def __init__(self, airports: Airports | None = None, path: Path = DB_FILE):
        self.airports = airports or Airports()
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._db()) as db, db:
            db.execute(_SCHEMA)

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    # ----------------------------------------------------------------- writes
    def _validate(self, day: str, origin: str, dest: str) -> tuple:
        try:
            d = date.fromisoformat((day or "").strip())
        except ValueError:
            raise ValueError(f"date must be YYYY-MM-DD, got {day!r}") from None
        o, t = self.airports.get(origin), self.airports.get(dest)
        if o is None:
            raise ValueError(f"unknown airport code {origin!r}")
        if t is None:
            raise ValueError(f"unknown airport code {dest!r}")
        if o.iata == t.iata:
            raise ValueError("origin and destination are the same airport")
        return d, o, t

    def _insert(self, db, d, o, t, extra: dict) -> int:
        km = great_circle_km(o.lat, o.lon, t.lat, t.lon)
        cur = db.execute(
            "INSERT INTO flights (date, origin, dest, airline, flight_number,"
            " aircraft, seat, notes, distance_km, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (d.isoformat(), o.iata, t.iata,
             *[(extra.get(k) or "").strip() for k in OPTIONAL],
             km, datetime.now(UTC).isoformat()))
        return cur.lastrowid

    def add(self, day: str, origin: str, dest: str, **extra) -> dict:
        d, o, t = self._validate(day, origin, dest)
        with closing(self._db()) as db, db:
            fid = self._insert(db, d, o, t, extra)
        return self.get(fid)

    def update(self, flight_id: int, day: str, origin: str, dest: str,
               **extra) -> dict | None:
        """Replace a flight's fields. Distance is recomputed from the airports.
        Returns None if there is no such flight."""
        d, o, t = self._validate(day, origin, dest)
        km = great_circle_km(o.lat, o.lon, t.lat, t.lon)
        with closing(self._db()) as db, db:
            changed = db.execute(
                "UPDATE flights SET date=?, origin=?, dest=?, airline=?,"
                " flight_number=?, aircraft=?, seat=?, notes=?, distance_km=?"
                " WHERE id=?",
                (d.isoformat(), o.iata, t.iata,
                 *[(extra.get(k) or "").strip() for k in OPTIONAL],
                 km, flight_id)).rowcount
        return self.get(flight_id) if changed else None

    def delete(self, flight_id: int) -> bool:
        with closing(self._db()) as db, db:
            return db.execute("DELETE FROM flights WHERE id = ?",
                              (flight_id,)).rowcount > 0

    def import_csv(self, text: str) -> dict:
        """Add every valid row; report the rest by line number. A row that
        matches an existing flight (date, route, flight number) is skipped, so
        importing the same file twice is harmless."""
        reader = csv.reader(io.StringIO(text.lstrip("﻿")))
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("the file is empty") from None
        cols = [_ALIASES.get(h.strip().lower()) for h in header]
        missing = [c for c in ("date", "from", "to") if c not in cols]
        if missing:
            raise ValueError(
                "missing column(s): " + ", ".join(missing)
                + ". The first row must be a header like: "
                + ",".join(TEMPLATE_COLUMNS))

        added = skipped = 0
        errors: list[dict] = []
        with closing(self._db()) as db, db:
            seen = {(r["date"], r["origin"], r["dest"], r["flight_number"].upper())
                    for r in db.execute("SELECT * FROM flights")}
            for line, raw in enumerate(reader, start=2):
                if not any(c.strip() for c in raw):
                    continue
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
                self._insert(db, d, o, t, row)
                added += 1
        return {"added": added, "skipped": skipped, "errors": errors}

    # ------------------------------------------------------------------ reads
    def _row(self, r: sqlite3.Row) -> dict:
        o, t = self.airports.get(r["origin"]), self.airports.get(r["dest"])
        return {
            "id": r["id"], "date": r["date"],
            "from": o.to_json() if o else {"iata": r["origin"]},
            "to": t.to_json() if t else {"iata": r["dest"]},
            **{k: r[k] for k in OPTIONAL},
            "distance_km": round(r["distance_km"], 1),
            "distance_mi": round(r["distance_km"] / KM_PER_MILE, 1),
        }

    def get(self, flight_id: int) -> dict | None:
        with closing(self._db()) as db:
            r = db.execute("SELECT * FROM flights WHERE id = ?",
                           (flight_id,)).fetchone()
        return self._row(r) if r else None

    def list(self) -> list[dict]:
        with closing(self._db()) as db:
            rows = db.execute(
                "SELECT * FROM flights ORDER BY date DESC, id DESC").fetchall()
        return [self._row(r) for r in rows]

    def stats(self, flights: list[dict] | None = None) -> dict:
        flights = self.list() if flights is None else flights
        codes = {f[end]["iata"] for f in flights for end in ("from", "to")}
        countries = {f[end].get("country") for f in flights
                     for end in ("from", "to")} - {None, ""}
        km = sum(f["distance_km"] for f in flights)
        longest = max(flights, key=lambda f: f["distance_km"], default=None)
        return {
            "flights": len(flights),
            "distance_km": round(km),
            "distance_mi": round(km / KM_PER_MILE),
            "airports": len(codes),
            "countries": len(countries),
            "longest": ({"from": longest["from"]["iata"],
                         "to": longest["to"]["iata"],
                         "distance_mi": round(longest["distance_mi"])}
                        if longest else None),
        }

    def snapshot(self) -> dict:
        flights = self.list()
        return {"flights": flights, "stats": self.stats(flights)}


def template_csv() -> str:
    return ",".join(TEMPLATE_COLUMNS) + "\n"
