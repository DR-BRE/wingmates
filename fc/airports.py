"""Airport lookup. Data is OurAirports (public domain), filtered to airports
with an IATA code and stored in data/airports.csv.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "airports.csv"


@dataclass(frozen=True, slots=True)
class Airport:
    iata: str
    icao: str
    name: str
    city: str
    country: str        # ISO 3166 alpha-2
    lat: float
    lon: float
    size: int           # 3 large, 2 medium, 1 small

    def to_json(self) -> dict:
        return asdict(self)


class Airports:
    def __init__(self, path: Path = DATA_FILE):
        self.by_iata: dict[str, Airport] = {}
        self.by_icao: dict[str, Airport] = {}
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                a = Airport(r["iata"], r["icao"], r["name"], r["city"],
                            r["country"], float(r["lat"]), float(r["lon"]),
                            int(r["size"]))
                self.by_iata[a.iata] = a
                if a.icao:
                    self.by_icao[a.icao] = a

    def get(self, code: str) -> Airport | None:
        """Resolve an IATA (ATL) or ICAO (KATL) code."""
        code = (code or "").strip().upper()
        return self.by_iata.get(code) or self.by_icao.get(code)

    def search(self, q: str, limit: int = 8) -> list[Airport]:
        """Code, city or name lookup for autocomplete; big airports first."""
        q = (q or "").strip().lower()
        if not q:
            return []
        scored = []
        for a in self.by_iata.values():
            city, name = a.city.lower(), a.name.lower()
            if a.iata.lower() == q or a.icao.lower() == q:
                rank = 0
            elif a.iata.lower().startswith(q):
                rank = 1
            elif city.startswith(q):
                rank = 2
            elif q in name or q in city:
                rank = 3
            else:
                continue
            scored.append((rank, -a.size, a.iata, a))
        scored.sort(key=lambda s: s[:3])
        return [s[3] for s in scored[:limit]]
