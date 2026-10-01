"""Feed clients. Vendor field names stop in this file.

Primary:  adsb.lol      — community ADS-B aggregator, no key, rich fields
Fallback: OpenSky       — volunteer network, thinner fields, gappier coverage

Both are free and community-run. Be a good citizen: the poller below rate-limits
itself, sets a real User-Agent, and backs off hard on errors. Neither feed is
licensed for commercial redistribution — OpenSky's terms are explicitly
non-commercial — so this is a personal tool, not a product.

What a free ADS-B feed cannot give you, at any polling rate: scheduled times,
gates, terminals, codeshares, cancellations, baggage claim. Those live in
airline/GDS feeds behind enterprise contracts. Everything the tracker derives
below is derived from where the metal actually is.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Iterable

from .schema import FlightKey, Position

UA = "wingmates/1.0 (personal flight tracker; contact: local user)"
TIMEOUT = 12
RATE_LIMIT_COOLDOWN_S = 300     # a 429 is the feed telling us to stop; listen


class FeedError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status

    @property
    def rate_limited(self) -> bool:
        return self.status == 429


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                              "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise FeedError(f"HTTP {e.code} from {url}", status=e.code) from e
    except Exception as e:                        # noqa: BLE001
        raise FeedError(f"{type(e).__name__}: {e}") from e


def _alt(raw) -> tuple[int | None, bool]:
    """adsb.lol encodes on-ground as the literal string 'ground' in alt_baro."""
    if raw == "ground":
        return (0, True)
    if isinstance(raw, (int, float)):
        return (int(raw), False)
    return (None, False)


# ---------------------------------------------------------------------------
# adsb.lol
# ---------------------------------------------------------------------------

class AdsbLol:
    name = "adsb.lol"
    BASE = "https://api.adsb.lol/v2"

    def _to_position(self, a: dict, now: datetime) -> Position | None:
        callsign = (a.get("flight") or "").strip()
        if not callsign:
            return None
        alt, ground = _alt(a.get("alt_baro"))
        seen = float(a.get("seen") or 0.0)
        return Position(
            key=FlightKey(callsign, now.date()),
            source=self.name,
            observed_at=datetime.fromtimestamp(now.timestamp() - seen, tz=UTC),
            received_at=now,
            lat=a.get("lat"), lon=a.get("lon"),
            on_ground=ground,
            altitude_ft=alt,
            ground_speed_kt=a.get("gs"),
            vertical_rate_fpm=(a.get("baro_rate") if a.get("baro_rate") is not None
                               else a.get("geom_rate")),
            track_deg=a.get("track"),
            registration=(a.get("r") or "").strip() or None,
            aircraft_type=(a.get("t") or "").strip() or None,
            squawk=a.get("squawk"),
            emergency=a.get("emergency"),
            hex_id=a.get("hex"),
            seen_s=seen,
        )

    def by_callsign(self, callsign: str) -> Position | None:
        d = _get(f"{self.BASE}/callsign/{callsign.upper()}")
        now = datetime.now(UTC)
        for a in d.get("ac") or []:
            if (p := self._to_position(a, now)) is not None:
                return p
        return None

    def by_registration(self, reg: str) -> Position | None:
        d = _get(f"{self.BASE}/registration/{reg.upper()}")
        now = datetime.now(UTC)
        for a in d.get("ac") or []:
            if (p := self._to_position(a, now)) is not None:
                return p
        return None

    def by_hex(self, hexid: str) -> Position | None:
        d = _get(f"{self.BASE}/hex/{hexid.lower()}")
        now = datetime.now(UTC)
        for a in d.get("ac") or []:
            if (p := self._to_position(a, now)) is not None:
                return p
        return None

    def nearby(self, lat: float, lon: float, dist_nm: int = 50) -> list[Position]:
        d = _get(f"{self.BASE}/lat/{lat:.4f}/lon/{lon:.4f}/dist/{int(dist_nm)}")
        now = datetime.now(UTC)
        out = []
        for a in d.get("ac") or []:
            if (p := self._to_position(a, now)) is not None:
                out.append(p)
        return out


# ---------------------------------------------------------------------------
# OpenSky — the warm second source. Thinner: no registration, no type, no squawk.
# ---------------------------------------------------------------------------

class OpenSky:
    name = "opensky"
    BASE = "https://opensky-network.org/api"

    def _to_position(self, s: list, now: datetime) -> Position | None:
        callsign = (s[1] or "").strip()
        if not callsign:
            return None
        alt_m = s[13] if s[13] is not None else s[7]
        return Position(
            key=FlightKey(callsign, now.date()),
            source=self.name,
            observed_at=datetime.fromtimestamp(s[3] or now.timestamp(), tz=UTC),
            received_at=now,
            lat=s[6], lon=s[5],
            on_ground=bool(s[8]),
            altitude_ft=int(alt_m * 3.28084) if alt_m is not None else None,
            ground_speed_kt=round(s[9] * 1.94384, 1) if s[9] is not None else None,
            vertical_rate_fpm=int(s[11] * 196.85) if s[11] is not None else None,
            track_deg=s[10],
            hex_id=s[0],
            seen_s=max(0.0, now.timestamp() - (s[4] or now.timestamp())),
        )

    def nearby(self, lat: float, lon: float, dist_nm: int = 50) -> list[Position]:
        d = dist_nm / 60.0
        url = (f"{self.BASE}/states/all?lamin={lat - d:.4f}&lomin={lon - d:.4f}"
               f"&lamax={lat + d:.4f}&lomax={lon + d:.4f}")
        data = _get(url)
        now = datetime.now(UTC)
        out = []
        for s in data.get("states") or []:
            if (p := self._to_position(s, now)) is not None:
                out.append(p)
        return out

    def by_callsign(self, callsign: str) -> Position | None:
        """OpenSky has no callsign endpoint, so this is a global scan — slow and
        rate-limited. Fallback only."""
        data = _get(f"{self.BASE}/states/all")
        now = datetime.now(UTC)
        want = callsign.upper().strip()
        for s in data.get("states") or []:
            if (s[1] or "").strip().upper() == want:
                return self._to_position(s, now)
        return None


# ---------------------------------------------------------------------------
# Failover wrapper. A dark second source is a fiction; this one is exercised
# every time the primary errors, and the active source is reported to the UI.
# ---------------------------------------------------------------------------

class Feed:
    def __init__(self):
        self.primary = AdsbLol()
        self.secondary = OpenSky()
        self.active = self.primary.name
        self.errors: list[str] = []
        self._cooldown_until = 0.0

    def _providers(self):
        if time.time() < self._cooldown_until:
            return [self.secondary, self.primary]
        return [self.primary, self.secondary]

    def _try(self, method: str, *args):
        last = None
        for prov in self._providers():
            fn = getattr(prov, method, None)
            if fn is None:
                continue
            try:
                result = fn(*args)
                self.active = prov.name
                return result
            except FeedError as e:
                last = e
                self.errors.append(f"{datetime.now(UTC).isoformat()} {prov.name}: {e}")
                del self.errors[:-20]
                if prov is self.primary:
                    # A 429 means we were genuinely too fast — back off far
                    # harder than for a transient error, and stay off.
                    self._cooldown_until = time.time() + (
                        RATE_LIMIT_COOLDOWN_S if e.rate_limited else 60)
        if last:
            raise last
        return None

    def by_callsign(self, cs: str) -> Position | None:
        return self._try("by_callsign", cs)

    def by_registration(self, reg: str) -> Position | None:
        return self._try("by_registration", reg)

    def nearby(self, lat: float, lon: float, dist_nm: int = 50) -> list[Position]:
        return self._try("nearby", lat, lon, dist_nm) or []
