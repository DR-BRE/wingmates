"""Phase detection from position reports alone.

With no schedule feed, every state transition has to be derived from where the
metal is and how fast it is moving. That makes hysteresis mandatory rather than
optional: real ADS-B drops the ground bit for a sample or two while an aircraft
is still on the taxiway, and a naive machine turns each flicker into a "Departed"
push. Every air/ground transition therefore needs CONFIRM consecutive samples
before it becomes an event.

Emergency squawks are the one exception — they fire on the first sample, because
a delayed 7700 alert is worthless.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .schema import (LOUD, Event, EventType, FlightState, Phase, Position,
                     Vertical)

CONFIRM = 2                 # consecutive samples required for an air/ground flip
STALE_AFTER = timedelta(minutes=4)
TAXI_SPEED_KT = 4.0
VERT_THRESHOLD_FPM = 350
CRUISE_MIN_FT = 18_000
MILESTONES = (10_000, 18_000, 30_000)


def _fmt_alt(ft: int | None) -> str:
    return f"{ft:,} ft" if ft else "—"


def _event(st: FlightState, t: EventType, at: datetime, title: str,
           detail: str, **data) -> Event:
    return Event(key=st.key, type=t, at=at, title=title, detail=detail,
                 loud=t in LOUD, data=data)


def _classify(p: Position, st: FlightState) -> Phase:
    """Instantaneous reading — not yet the committed phase."""
    if p.on_ground:
        slow = (p.ground_speed_kt or 0) < TAXI_SPEED_KT
        if st.has_been_airborne:
            return Phase.ARRIVED if slow else Phase.TAXI_IN
        return Phase.AT_GATE if slow else Phase.TAXI_OUT
    return Phase.AIRBORNE


def _vertical(p: Position) -> Vertical:
    if p.on_ground:
        return Vertical.GROUND
    rate = p.vertical_rate_fpm or 0
    if rate > VERT_THRESHOLD_FPM:
        return Vertical.CLIMB
    if rate < -VERT_THRESHOLD_FPM:
        return Vertical.DESCENT
    return Vertical.CRUISE


_TRANSITION_EVENT = {
    (Phase.AT_GATE,  Phase.TAXI_OUT): (EventType.PUSHBACK, "Pushed back",
                                       "Your aircraft is moving under its own power."),
    (Phase.TAXI_OUT, Phase.AIRBORNE): (EventType.DEPARTED, "Departed", "Wheels up."),
    (Phase.AT_GATE,  Phase.AIRBORNE): (EventType.DEPARTED, "Departed", "Wheels up."),
    (Phase.AIRBORNE, Phase.TAXI_IN):  (EventType.LANDED, "Landed",
                                       "On the ground and taxiing in."),
    (Phase.AIRBORNE, Phase.ARRIVED):  (EventType.LANDED, "Landed", "On the ground."),
    (Phase.TAXI_IN,  Phase.ARRIVED):  (EventType.ON_BLOCK, "At the gate",
                                       "Doors shortly."),
}


def apply(st: FlightState, p: Position) -> list[Event]:
    """Fold one position report into the flight state. Returns new events."""
    events: list[Event] = []
    first = st.last is None

    # --- identity enrichment (a later sample often carries what the first lacked)
    st.registration = p.registration or st.registration
    st.aircraft_type = p.aircraft_type or st.aircraft_type
    st.hex_id = p.hex_id or st.hex_id

    if first:
        st.first_seen = p.observed_at
        events.append(_event(
            st, EventType.ACQUIRED, p.observed_at, "Tracking started",
            f"{st.registration or 'aircraft'} "
            f"{('(' + st.aircraft_type + ')') if st.aircraft_type else ''}".strip()
            + f" · {_fmt_alt(p.altitude_ft)}",
            source=p.source))

    # --- signal reacquisition
    if st.phase is Phase.SIGNAL_LOST:
        events.append(_event(st, EventType.SIGNAL_REACQUIRED, p.observed_at,
                             "Signal reacquired", "Back in coverage."))
        st.phase = Phase.UNKNOWN
        st._pending = None

    # --- emergency: first sample, no confirmation, no hysteresis
    if p.is_emergency() and st.squawk != p.squawk:
        events.append(_event(
            st, EventType.EMERGENCY_SQUAWK, p.observed_at,
            f"Emergency squawk {p.squawk}",
            {"7500": "Unlawful interference.", "7600": "Radio failure.",
             "7700": "General emergency."}.get(p.squawk or "", "Emergency declared."),
            squawk=p.squawk))
    elif p.squawk and st.squawk and p.squawk != st.squawk:
        events.append(_event(st, EventType.SQUAWK_CHANGED, p.observed_at,
                             "Squawk changed",
                             f"{st.squawk} → {p.squawk}", squawk=p.squawk))
    st.squawk = p.squawk or st.squawk

    # --- phase, with confirmation
    observed = _classify(p, st)
    if observed != st.phase:
        pending_phase, count = st._pending or (observed, 0)
        if pending_phase == observed:
            count += 1
        else:
            pending_phase, count = observed, 1
        # Ground/air flips need confirmation; ground-speed-only changes do not.
        crosses_air_ground = (observed is Phase.AIRBORNE) != (st.phase is Phase.AIRBORNE)
        needed = CONFIRM if crosses_air_ground and not first else 1
        if count >= needed:
            prev = st.phase
            st.phase = observed
            st._pending = None
            if observed is Phase.AIRBORNE:
                st.has_been_airborne = True
            if spec := _TRANSITION_EVENT.get((prev, observed)):
                etype, title, detail = spec
                events.append(_event(st, etype, p.observed_at, title, detail,
                                     previous_phase=str(prev)))
        else:
            st._pending = (pending_phase, count)
    else:
        st._pending = None

    # --- vertical profile
    vert = _vertical(p)
    if vert != st.vertical:
        prev_vert, st.vertical = st.vertical, vert
        if (prev_vert is Vertical.CLIMB and vert is Vertical.CRUISE
                and (p.altitude_ft or 0) >= CRUISE_MIN_FT):
            events.append(_event(st, EventType.TOP_OF_CLIMB, p.observed_at,
                                 "Reached cruise",
                                 f"Level at {_fmt_alt(p.altitude_ft)}."))
        elif vert is Vertical.DESCENT and (p.altitude_ft or 0) >= CRUISE_MIN_FT:
            events.append(_event(st, EventType.DESCENT_STARTED, p.observed_at,
                                 "Descent started",
                                 "Your flight has begun its descent."))

    # --- climb milestones, emitted once each on the way up
    if p.altitude_ft and vert is Vertical.CLIMB:
        for m in MILESTONES:
            if st.max_altitude_ft < m <= p.altitude_ft:
                events.append(_event(st, EventType.ALTITUDE_MILESTONE,
                                     p.observed_at, f"Passing {m // 1000},000 ft",
                                     f"Climbing through {_fmt_alt(p.altitude_ft)}.",
                                     altitude_ft=m))

    # --- running maxima and trail
    if p.altitude_ft:
        st.max_altitude_ft = max(st.max_altitude_ft, p.altitude_ft)
    if p.ground_speed_kt:
        st.max_speed_kt = max(st.max_speed_kt, p.ground_speed_kt)
    if p.lat is not None and p.lon is not None:
        pt = (round(p.lat, 5), round(p.lon, 5))
        if not st.trail or st.trail[-1] != pt:
            st.trail.append(pt)
            del st.trail[:-600]

    st.last = p
    st.last_seen = p.observed_at
    return events


def check_stale(st: FlightState, now: datetime) -> list[Event]:
    """Called on a timer. Silence is itself information — say so rather than
    showing a confidently stale position."""
    if st.last_seen is None or st.phase in (Phase.SIGNAL_LOST, Phase.ARRIVED):
        return []
    if now - st.last_seen > STALE_AFTER:
        gap = int((now - st.last_seen).total_seconds() // 60)
        st.phase = Phase.SIGNAL_LOST
        return [_event(st, EventType.SIGNAL_LOST, now, "Signal lost",
                       f"No position for {gap} min — likely out of "
                       f"receiver coverage.", gap_min=gap)]
    return []
