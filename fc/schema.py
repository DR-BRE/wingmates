"""Core types for the live tracker.

Identity note: with an ADS-B-only feed there is no schedule record, so a leg is
keyed by callsign + UTC date rather than by operating carrier + local departure
date. That is a real downgrade from the production design — it cannot survive a
midnight-local rollover the way a schedule-backed key can — and it is the first
thing that changes when a schedule feed is added.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class FlightKey:
    callsign: str          # "DAL983"
    day: date              # UTC date of first acquisition

    def __str__(self) -> str:
        return f"{self.callsign}/{self.day.isoformat()}"

    @staticmethod
    def parse(s: str) -> "FlightKey":
        cs, d = s.split("/")
        return FlightKey(cs, date.fromisoformat(d))


class Phase(enum.StrEnum):
    UNKNOWN     = "unknown"
    AT_GATE     = "at_gate"
    TAXI_OUT    = "taxi_out"
    AIRBORNE    = "airborne"
    TAXI_IN     = "taxi_in"
    ARRIVED     = "arrived"
    SIGNAL_LOST = "signal_lost"


class Vertical(enum.StrEnum):
    GROUND  = "ground"
    CLIMB   = "climb"
    CRUISE  = "cruise"
    DESCENT = "descent"


class EventType(enum.StrEnum):
    ACQUIRED           = "Acquired"
    PUSHBACK           = "Pushback"
    DEPARTED           = "Departed"
    TOP_OF_CLIMB       = "TopOfClimb"
    DESCENT_STARTED    = "DescentStarted"
    LANDED             = "Landed"
    ON_BLOCK           = "OnBlock"
    SIGNAL_LOST        = "SignalLost"
    SIGNAL_REACQUIRED  = "SignalReacquired"
    EMERGENCY_SQUAWK   = "EmergencySquawk"
    SQUAWK_CHANGED     = "SquawkChanged"
    ALTITUDE_MILESTONE = "AltitudeMilestone"


# Only these interrupt. Everything else lands in the feed silently — the same
# materiality split the production design puts in its alert engine.
LOUD = {EventType.DEPARTED, EventType.LANDED, EventType.DESCENT_STARTED,
        EventType.EMERGENCY_SQUAWK, EventType.ON_BLOCK}

EMERGENCY_SQUAWKS = {"7500", "7600", "7700"}


@dataclass(frozen=True, slots=True)
class Position:
    """One normalized ADS-B observation. Vendor field names stop here."""
    key: FlightKey
    source: str
    observed_at: datetime       # when the aircraft reported
    received_at: datetime
    lat: float | None = None
    lon: float | None = None
    on_ground: bool = False
    altitude_ft: int | None = None
    ground_speed_kt: float | None = None
    vertical_rate_fpm: int | None = None
    track_deg: float | None = None
    registration: str | None = None
    aircraft_type: str | None = None
    squawk: str | None = None
    emergency: str | None = None
    hex_id: str | None = None
    seen_s: float = 0.0

    def is_emergency(self) -> bool:
        return (self.squawk in EMERGENCY_SQUAWKS
                or (self.emergency not in (None, "", "none")))


@dataclass(frozen=True, slots=True)
class Event:
    key: FlightKey
    type: EventType
    at: datetime
    title: str
    detail: str
    loud: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"flight": self.key.callsign, "key": str(self.key),
                "type": str(self.type), "at": self.at.isoformat(),
                "title": self.title, "detail": self.detail,
                "loud": self.loud, "data": self.data}


@dataclass
class FlightState:
    key: FlightKey
    phase: Phase = Phase.UNKNOWN
    vertical: Vertical = Vertical.GROUND
    registration: str | None = None
    aircraft_type: str | None = None
    hex_id: str | None = None
    squawk: str | None = None
    last: Position | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    max_altitude_ft: int = 0
    max_speed_kt: float = 0.0
    trail: list[tuple[float, float]] = field(default_factory=list)
    has_been_airborne: bool = False
    # Hysteresis: real ADS-B flips on_ground spuriously, so a transition needs
    # confirmation before it becomes an event people get pushed about.
    _pending: tuple[Phase, int] | None = None

    def to_json(self) -> dict:
        p = self.last
        return {
            "key": str(self.key),
            "callsign": self.key.callsign,
            "phase": str(self.phase),
            "vertical": str(self.vertical),
            "registration": self.registration,
            "aircraft_type": self.aircraft_type,
            "hex": self.hex_id,
            "squawk": self.squawk,
            "lat": p.lat if p else None,
            "lon": p.lon if p else None,
            "altitude_ft": p.altitude_ft if p else None,
            "ground_speed_kt": p.ground_speed_kt if p else None,
            "vertical_rate_fpm": p.vertical_rate_fpm if p else None,
            "track_deg": p.track_deg if p else None,
            "on_ground": p.on_ground if p else None,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "stale_s": round(
                (datetime.now(self.last_seen.tzinfo) - self.last_seen).total_seconds(), 1
            ) if self.last_seen else None,
            "max_altitude_ft": self.max_altitude_ft,
            "max_speed_kt": round(self.max_speed_kt, 1),
            "trail": self.trail[-400:],
            "emergency": bool(p and p.is_emergency()),
        }
