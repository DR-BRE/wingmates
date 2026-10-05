"""Pulling flights out of airline confirmation emails.

Three extraction paths, tried best-first, each reporting how it found a flight
so the review screen can show its working:

1. **JSON-LD** — airlines embed schema.org `FlightReservation` markup so Google
   can surface itineraries in Gmail and Calendar. It is structured, carries ISO
   timestamps and IATA codes, and needs no guessing. When present it is as good
   as data gets, and it is free.
2. **Microdata** — the same schema expressed as HTML attributes. Older, rarer,
   same confidence once parsed.
3. **Text patterns** — a regex fallback over the visible words. Honest about
   being a guess: dates are genuinely ambiguous in prose (03/04 is two different
   days depending on the airline's locale), so everything from this path is
   marked `medium` and must be confirmed by a human.

Nothing here touches the network or the database. It takes an email and returns
candidates; deciding what to do with them belongs to the caller. That split is
what makes this file exhaustively testable against saved fixtures.
"""
from __future__ import annotations

import html as html_mod
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

# Confidence levels. Only `high` may ever be pre-ticked on the review screen.
HIGH = "high"
MEDIUM = "medium"


@dataclass
class Candidate:
    """One flight we think the person took. Deliberately mirrors the columns
    `History.add` expects, so importing is a field-for-field handoff."""
    date: str                      # ISO yyyy-mm-dd, local to the origin airport
    origin: str                    # IATA
    dest: str                      # IATA
    airline: str = ""
    flight_number: str = ""
    confidence: str = MEDIUM
    method: str = "text"
    source_subject: str = ""
    source_id: str = ""

    def key(self) -> tuple:
        """Identity for de-duplication. Flight number is deliberately excluded:
        the same leg often appears with the operating number in one email and a
        codeshare number in another, and they are not two flights."""
        return (self.date, self.origin, self.dest)

    def to_json(self) -> dict:
        return {
            "date": self.date, "from": self.origin, "to": self.dest,
            "airline": self.airline, "flight_number": self.flight_number,
            "confidence": self.confidence, "method": self.method,
            "subject": self.source_subject, "source_id": self.source_id,
        }


# --------------------------------------------------------------------------
# schema.org helpers
# --------------------------------------------------------------------------

def _walk(node: Any) -> Iterable[dict]:
    """Yield every dict in a nested JSON structure.

    Airlines nest their markup inconsistently — a bare object, a list, an
    `@graph`, a reservation wrapped in another reservation. Walking the whole
    tree is cheaper than trying to predict the shape.
    """
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _types(node: dict) -> set[str]:
    raw = node.get("@type") or node.get("type") or ""
    values = raw if isinstance(raw, list) else [raw]
    return {str(v).rsplit("/", 1)[-1].lower() for v in values}


def _iata(node: Any) -> str:
    """An airport may be a string, or an object with iataCode, or an object with
    only a name. Take a code where one exists and ignore the rest."""
    if isinstance(node, str):
        return node.strip().upper() if re.fullmatch(r"[A-Za-z]{3}", node.strip()) else ""
    if isinstance(node, dict):
        for field_name in ("iataCode", "iatacode", "code"):
            value = node.get(field_name)
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z]{3}", value.strip()):
                return value.strip().upper()
    return ""


def _airline(node: Any) -> tuple[str, str]:
    """Returns (display name, IATA prefix)."""
    if isinstance(node, str):
        return node.strip(), ""
    if isinstance(node, dict):
        name = str(node.get("name") or "").strip()
        code = str(node.get("iataCode") or node.get("iatacode") or "").strip().upper()
        return name, code
    return "", ""


def _iso_date(value: Any) -> str:
    """schema.org departureTime is an ISO 8601 instant. Keep the *local* date as
    written — an 23:50 departure must not slide to the next day because the
    offset pushes it past midnight UTC."""
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return ""
    try:
        return date(int(match[1]), int(match[2]), int(match[3])).isoformat()
    except ValueError:
        return ""


def _flight_from_schema(flight: dict) -> tuple[str, str, str, str, str]:
    """(date, origin, dest, airline, flight_number) from a schema.org Flight."""
    origin = _iata(flight.get("departureAirport"))
    dest = _iata(flight.get("arrivalAirport"))
    day = _iso_date(flight.get("departureTime"))
    name, code = _airline(flight.get("airline"))
    number = str(flight.get("flightNumber") or "").strip().upper()
    # Airlines split this two ways: flightNumber "110" with a separate airline
    # code, or flightNumber "AA110" carrying the prefix already.
    if number and code and not number.startswith(code):
        number = f"{code}{number}"
    return day, origin, dest, name or code, number


# --------------------------------------------------------------------------
# Path 1 — JSON-LD
# --------------------------------------------------------------------------

_SCRIPT_RE = re.compile(
    r'<script[^>]+type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL)


def from_json_ld(html: str) -> list[tuple]:
    found: list[tuple] = []
    for raw in _SCRIPT_RE.findall(html or ""):
        try:
            data = json.loads(html_mod.unescape(raw.strip()))
        except (json.JSONDecodeError, ValueError):
            continue
        for node in _walk(data):
            if "flight" not in _types(node):
                continue
            day, origin, dest, airline, number = _flight_from_schema(node)
            if day and origin and dest:
                found.append((day, origin, dest, airline, number))
    return found


# --------------------------------------------------------------------------
# Path 2 — microdata
# --------------------------------------------------------------------------

_ITEMPROP_RE = re.compile(
    r'<(?:meta|span|div|time|link)[^>]*itemprop\s*=\s*["\']([A-Za-z]+)["\'][^>]*?'
    r'(?:content|datetime)\s*=\s*["\']([^"\']*)["\']',
    re.IGNORECASE)
_FLIGHT_BLOCK_RE = re.compile(
    r'itemtype\s*=\s*["\'][^"\']*schema\.org/Flight["\']', re.IGNORECASE)


def from_microdata(html: str) -> list[tuple]:
    if not html or not _FLIGHT_BLOCK_RE.search(html):
        return []
    props: dict[str, str] = {}
    for name, value in _ITEMPROP_RE.findall(html):
        props.setdefault(name, value.strip())

    day = _iso_date(props.get("departureTime", ""))
    origin = props.get("departureAirport", "").strip().upper()
    dest = props.get("arrivalAirport", "").strip().upper()
    if not (re.fullmatch(r"[A-Z]{3}", origin) and re.fullmatch(r"[A-Z]{3}", dest)):
        return []
    number = props.get("flightNumber", "").strip().upper()
    airline = props.get("name", "").strip()
    if day:
        return [(day, origin, dest, airline, number)]
    return []


# --------------------------------------------------------------------------
# Path 3 — text patterns
# --------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\xa0]+")

# "SFO to JFK", "SFO - JFK", "SFO → JFK"
_ROUTE_RE = re.compile(
    r"\b([A-Z]{3})\b\s*(?:to|-|–|—|→|>)\s*\b([A-Z]{3})\b")
# "AA 110", "BA2490", "UA  1"
_FLIGHT_RE = re.compile(r"\b([A-Z]{2}|[A-Z]\d|\d[A-Z])\s?(\d{1,4})\b")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_LONG_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
    r"\s+(\d{4})\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
    r"\s+(\d{1,2}),?\s+(\d{4})\b", re.IGNORECASE)

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def plain_text(html: str, text: str) -> str:
    """Prefer the plain part; fall back to crudely stripping tags."""
    if text and text.strip():
        return _WS_RE.sub(" ", text)
    stripped = _TAG_RE.sub(" ", html or "")
    return _WS_RE.sub(" ", html_mod.unescape(stripped))


def _find_date(blob: str) -> str:
    """Only unambiguous dates. A bare 03/04/2027 is deliberately ignored —
    guessing its locale is how a tracker quietly files flights on wrong days."""
    if match := _ISO_DATE_RE.search(blob):
        try:
            return date(int(match[1]), int(match[2]), int(match[3])).isoformat()
        except ValueError:
            pass
    if match := _LONG_DATE_RE.search(blob):
        try:
            if match[1]:
                day, month, year = int(match[1]), _MONTHS[match[2][:3].lower()], int(match[3])
            else:
                month, day, year = _MONTHS[match[4][:3].lower()], int(match[5]), int(match[6])
            return date(year, month, day).isoformat()
        except (ValueError, KeyError):
            pass
    return ""


def from_text(blob: str) -> list[tuple]:
    route = _ROUTE_RE.search(blob or "")
    if not route:
        return []
    day = _find_date(blob)
    if not day:
        return []
    number = ""
    if flight := _FLIGHT_RE.search(blob):
        number = f"{flight[1]}{flight[2]}"
    return [(day, route[1], route[2], "", number)]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

# Words that mean "you might fly" rather than "you flew". Marketing mail is the
# main source of bogus candidates, and a fare sale quotes real routes and dates.
_PROMO_MARKERS = (
    "deals", "sale", "fares from", "book now", "save up to", "offer ends",
    "unsubscribe from our marketing", "explore destinations", "price drop",
)


def looks_promotional(subject: str, blob: str) -> bool:
    haystack = f"{subject} {blob[:2000]}".lower()
    return sum(marker in haystack for marker in _PROMO_MARKERS) >= 2


def extract(subject: str = "", html: str = "", text: str = "",
            source_id: str = "") -> list[Candidate]:
    """An email in, zero or more candidate flights out, best method first."""
    blob = plain_text(html, text)
    if looks_promotional(subject, blob):
        return []

    attempts = (
        (from_json_ld(html), "jsonld", HIGH),
        (from_microdata(html), "microdata", HIGH),
        (from_text(blob), "text", MEDIUM),
    )

    out: list[Candidate] = []
    seen: set[tuple] = set()
    for rows, method, confidence in attempts:
        for day, origin, dest, airline, number in rows:
            if origin == dest:
                continue                      # a leg to itself is a parse error
            candidate = Candidate(
                date=day, origin=origin, dest=dest, airline=airline,
                flight_number=number, confidence=confidence, method=method,
                source_subject=subject, source_id=source_id)
            if candidate.key() in seen:
                continue                      # a better method already has it
            seen.add(candidate.key())
            out.append(candidate)
        if out and confidence is HIGH:
            # Structured markup covered this email; don't let regex add noise.
            break
    return out


def dedupe(candidates: Iterable[Candidate],
           already_flown: Iterable[tuple]) -> list[Candidate]:
    """Drop anything already in the person's log, and collapse repeats.

    Confirmation, check-in, and boarding-pass emails all describe the same leg,
    so without this a single trip arrives three times.
    """
    known = set(already_flown)
    out: list[Candidate] = []
    for candidate in candidates:
        if candidate.key() in known:
            continue
        known.add(candidate.key())
        out.append(candidate)
    return sorted(out, key=lambda c: (c.date, c.origin))
