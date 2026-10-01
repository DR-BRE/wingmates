"""Tracker: the poll loop, the flight registry, the alert feed, persistence.

Cost shape note. The production design processes every leg the world operates
once and consults a subscription index only at fan-out, so compute is flat
against user count. A free feed has no firehose to subscribe to, so this polls
per tracked flight instead — the very design the plan argues against. It is the
right call here (one user, a handful of flights) and the wrong call at scale,
which is exactly why a real product buys a stream.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import UTC, date, datetime
from pathlib import Path

from .adsb import Feed, FeedError
from .schema import Event, EventType, FlightKey, FlightState, Phase
from .statemachine import apply, check_stale

STATE_DIR = Path.home() / ".flighty-clone"
STATE_FILE = STATE_DIR / "state.json"

# These are deliberately conservative. adsb.lol and OpenSky are free and
# community-run; an aggressive poller gets a 429 (observed during development)
# and deserves it. One sweep every 20s across a handful of flights is roughly
# 0.1 req/s — well inside any reasonable budget.
POLL_INTERVAL_S = 20          # per full sweep
MIN_GAP_BETWEEN_CALLS_S = 2.0  # spacing between per-flight calls
MAX_TRACKED = 12
ALERT_HISTORY = 400


class Tracker:
    def __init__(self, feed: Feed | None = None):
        self.feed = feed or Feed()
        self.flights: dict[FlightKey, FlightState] = {}
        self.alerts: list[Event] = []
        self.log: list[dict] = []          # completed flights ("Passport")
        self.lock = threading.RLock()
        self.running = False
        self.last_poll: datetime | None = None
        self.poll_count = 0
        self.unseen: dict[FlightKey, int] = {}
        self._thread: threading.Thread | None = None
        self.load()

    # ---------------------------------------------------------------- tracking
    def track(self, callsign: str) -> dict:
        callsign = callsign.upper().strip().replace(" ", "")
        if not callsign:
            raise ValueError("empty callsign")
        with self.lock:
            if len(self.flights) >= MAX_TRACKED:
                raise ValueError(f"tracking limit is {MAX_TRACKED} flights")
            existing = next((k for k in self.flights if k.callsign == callsign), None)
            if existing:
                return self.flights[existing].to_json()

        # Resolve immediately so the user gets a real answer, not a spinner.
        try:
            pos = self.feed.by_callsign(callsign)
        except FeedError as e:
            raise ValueError(f"feed unavailable: {e}") from e
        if pos is None:
            raise LookupError(
                f"{callsign} is not currently transmitting. ADS-B only sees "
                f"aircraft that are powered on and in receiver coverage — try "
                f"a flight that is airborne now.")

        with self.lock:
            st = FlightState(key=pos.key)
            self.flights[pos.key] = st
            self.unseen[pos.key] = 0
            self._record(apply(st, pos))
            self.save()
            return st.to_json()

    def untrack(self, key_str: str) -> bool:
        with self.lock:
            for k in list(self.flights):
                if str(k) == key_str or k.callsign == key_str.upper():
                    st = self.flights.pop(k)
                    self.unseen.pop(k, None)
                    self._archive(st)
                    self.save()
                    return True
            return False

    def _archive(self, st: FlightState) -> None:
        if st.first_seen is None:
            return
        self.log.insert(0, {
            "callsign": st.key.callsign,
            "day": st.key.day.isoformat(),
            "registration": st.registration,
            "aircraft_type": st.aircraft_type,
            "max_altitude_ft": st.max_altitude_ft,
            "max_speed_kt": round(st.max_speed_kt, 1),
            "first_seen": st.first_seen.isoformat(),
            "last_seen": st.last_seen.isoformat() if st.last_seen else None,
            "final_phase": str(st.phase),
            "trail_points": len(st.trail),
        })
        del self.log[200:]

    # ------------------------------------------------------------------- polls
    def poll_once(self) -> int:
        with self.lock:
            keys = list(self.flights)
        updated = 0
        for i, key in enumerate(keys):
            if i:
                time.sleep(MIN_GAP_BETWEEN_CALLS_S)
            try:
                pos = self.feed.by_callsign(key.callsign)
            except FeedError:
                continue
            with self.lock:
                st = self.flights.get(key)
                if st is None:
                    continue
                if pos is None:
                    self.unseen[key] = self.unseen.get(key, 0) + 1
                    self._record(check_stale(st, datetime.now(UTC)))
                else:
                    self.unseen[key] = 0
                    self._record(apply(st, pos))
                    updated += 1
        with self.lock:
            self.last_poll = datetime.now(UTC)
            self.poll_count += 1
            self.save()
        return updated

    def _record(self, events: list[Event]) -> None:
        if not events:
            return
        self.alerts = events[::-1] + self.alerts
        del self.alerts[ALERT_HISTORY:]
        for e in events:
            flag = "!" if e.loud else " "
            print(f"  [{flag}] {e.key.callsign:<8} {e.type:<18} {e.title}")

    def start(self) -> None:
        if self.running:
            return
        self.running = True

        def loop():
            while self.running:
                try:
                    self.poll_once()
                except Exception as e:                       # noqa: BLE001
                    print(f"  poll error: {type(e).__name__}: {e}")
                for _ in range(POLL_INTERVAL_S * 2):
                    if not self.running:
                        return
                    time.sleep(0.5)

        self._thread = threading.Thread(target=loop, daemon=True,
                                        name="tracker-poll")
        self._thread.start()

    def stop(self) -> None:
        self.running = False

    # ------------------------------------------------------------------ views
    def snapshot(self) -> dict:
        with self.lock:
            return {
                "flights": [st.to_json() for st in self.flights.values()],
                "alerts": [e.to_json() for e in self.alerts[:80]],
                "log": self.log[:50],
                "status": {
                    "source": self.feed.active,
                    "last_poll": self.last_poll.isoformat() if self.last_poll else None,
                    "poll_count": self.poll_count,
                    "tracked": len(self.flights),
                    "max_tracked": MAX_TRACKED,
                    "poll_interval_s": POLL_INTERVAL_S,
                    "feed_errors": self.feed.errors[-3:],
                },
            }

    def nearby(self, lat: float, lon: float, dist: int) -> list[dict]:
        out = []
        for p in self.feed.nearby(lat, lon, min(dist, 250)):
            out.append({
                "callsign": p.key.callsign, "registration": p.registration,
                "aircraft_type": p.aircraft_type, "lat": p.lat, "lon": p.lon,
                "altitude_ft": p.altitude_ft, "ground_speed_kt": p.ground_speed_kt,
                "track_deg": p.track_deg, "on_ground": p.on_ground,
                "squawk": p.squawk, "emergency": p.is_emergency(),
            })
        return out

    def where_is_aircraft(self, reg: str) -> dict | None:
        """'Where's my plane' — look up the airframe, not the flight number."""
        p = self.feed.by_registration(reg)
        if p is None:
            return None
        return {"callsign": p.key.callsign, "registration": p.registration,
                "aircraft_type": p.aircraft_type, "lat": p.lat, "lon": p.lon,
                "altitude_ft": p.altitude_ft, "ground_speed_kt": p.ground_speed_kt,
                "on_ground": p.on_ground, "track_deg": p.track_deg,
                "squawk": p.squawk}

    # ------------------------------------------------------------ persistence
    def save(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "flights": [
                {"key": str(k), "phase": str(st.phase),
                 "registration": st.registration, "aircraft_type": st.aircraft_type,
                 "hex": st.hex_id, "squawk": st.squawk,
                 "first_seen": st.first_seen.isoformat() if st.first_seen else None,
                 "last_seen": st.last_seen.isoformat() if st.last_seen else None,
                 "max_altitude_ft": st.max_altitude_ft,
                 "max_speed_kt": st.max_speed_kt,
                 "has_been_airborne": st.has_been_airborne,
                 "trail": st.trail[-400:]}
                for k, st in self.flights.items()
            ],
            "alerts": [e.to_json() for e in self.alerts[:ALERT_HISTORY]],
            "log": self.log,
        }
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(STATE_FILE)     # atomic: never leave a half-written state file

    def load(self) -> None:
        if not STATE_FILE.exists():
            return
        try:
            d = json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for f in d.get("flights", []):
            try:
                key = FlightKey.parse(f["key"])
            except (ValueError, KeyError):
                continue
            # Resume whatever was being tracked, whatever day it was acquired:
            # a long-running process keeps these flights, so a restart must
            # too. Untracking is the user's call and archives to the log.
            st = FlightState(key=key)
            st.phase = Phase(f.get("phase", "unknown"))
            st.registration = f.get("registration")
            st.aircraft_type = f.get("aircraft_type")
            st.hex_id = f.get("hex")
            st.squawk = f.get("squawk")
            st.max_altitude_ft = f.get("max_altitude_ft", 0)
            st.max_speed_kt = f.get("max_speed_kt", 0.0)
            st.has_been_airborne = f.get("has_been_airborne", False)
            st.trail = [tuple(p) for p in f.get("trail", [])]
            for fld in ("first_seen", "last_seen"):
                if f.get(fld):
                    setattr(st, fld, datetime.fromisoformat(f[fld]))
            self.flights[key] = st
        for a in d.get("alerts", []):
            try:
                self.alerts.append(Event(
                    key=FlightKey.parse(a["key"]), type=EventType(a["type"]),
                    at=datetime.fromisoformat(a["at"]), title=a["title"],
                    detail=a["detail"], loud=a.get("loud", False),
                    data=a.get("data", {})))
            except (ValueError, KeyError):
                continue
        self.log = d.get("log", [])
