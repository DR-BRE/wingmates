# Flighty Clone — live flight tracker

A working flight tracker: real ADS-B data, live map, a state machine that
derives departure/landing/descent from aircraft positions, and an alert feed.
Python stdlib only — **no pip install, no API key, no account.**

```
cd ~/flighty-clone
python3 run.py
```

Opens `http://127.0.0.1:8817`. Press `ctrl-c` to stop.

```
python3 run.py --port 9000     # different port
python3 run.py --no-browser    # don't auto-open
python3 -m unittest discover -s tests -t .   # 20 offline tests
```

## What it does

| | |
|---|---|
| **Track a flight** | By ADS-B callsign (`DAL983`, `BAW117`). Resolves against the live feed immediately — no spinner, no fake "pending" state. |
| **Live map** | Dark map, aircraft rotated to true track, position trails accumulating as it flies. |
| **Phase detection** | At gate → pushback → taxi → airborne (climb/cruise/descent) → landed → taxi in → at gate. Derived entirely from position reports. |
| **Alerts** | Departed, Landed, Descent started, Reached cruise, Pushed back, At the gate, altitude milestones. Loud events toast on screen. |
| **Emergency squawks** | 7500/7600/7700 detected and escalated on the *first* sample, no hysteresis delay. |
| **Where's my plane** | Look up an airframe by registration (`G-RUKB`) and see what it's flying as right now. |
| **Nearby radar** | Every aircraft within 90 nm of the map centre, one click to track any of them. |
| **Flight log** | Completed flights with max altitude, max speed, duration. |
| **Survives restart** | State persists to `~/.flighty-clone/state.json`, written atomically. |

## Data sources

| | Role | Gives |
|---|---|---|
| [adsb.lol](https://adsb.lol) | primary | callsign, registration, type, altitude, speed, vertical rate, track, squawk |
| [OpenSky](https://opensky-network.org) | fallback | position, altitude, speed, track (no registration or type) |

Failover is automatic and was **exercised for real during development**: adsb.lol
returned HTTP 429, the tracker switched to OpenSky mid-session, and tracked
flights kept updating. The status pill in the header always shows which feed is
live. A 429 now triggers a 5-minute cooldown, because a free community feed
saying "slow down" deserves to be listened to.

Polling is deliberately gentle: one sweep every 20 s, 2 s between per-flight
calls, 12 tracked flights maximum — roughly 0.1 requests/second.

## What it deliberately cannot do

This is the honest part. **Everything Flighty sells that isn't position data
requires a paid feed**, and no amount of code substitutes for it:

- **Gates, terminals, baggage claim** — airline/GDS feeds, not ADS-B.
- **Scheduled times**, and therefore **delays**. Without a schedule there is no
  "late" — only "where the aircraft is". This is the single biggest gap.
- **Cancellations** — a cancelled flight simply never appears on ADS-B, which is
  indistinguishable from an aircraft out of receiver coverage.
- **Codeshares** — ADS-B carries the operating callsign only, so a passenger
  booked on a marketing number has to know the operating one.
- **Push notifications to a phone** — alerts are in-app; real push needs an
  Apple Developer account and APNs.
- **Coverage gaps** — oceanic, polar, and much of Africa/Asia have thin or no
  community receiver coverage. Aircraft genuinely vanish there.

Flighty solves these with FlightAware Firehose plus schedule feeds, which is
enterprise-contract territory. The architecture here keeps that swap cheap: all
vendor field names stop inside `fc/adsb.py`, so adding a schedule provider means
a new client module and a wider `Position`, not a rewrite.

## Layout

```
run.py                  entry point — starts poller + server
fc/schema.py            FlightKey, Position, Phase, Event, FlightState
fc/adsb.py              feed clients + automatic failover
fc/statemachine.py      phase detection with hysteresis
fc/tracker.py           poll loop, registry, alert feed, persistence
fc/server.py            stdlib HTTP API + static serving
web/                    UI (Leaflet map, vanilla JS, no build step)
tests/                  20 offline tests — no network required
```

## API

```
GET  /api/state                      everything: flights, alerts, log, status
POST /api/track      {callsign}      start tracking
POST /api/untrack    {key}           stop, and archive to the log
POST /api/poll                       force a feed poll now
GET  /api/nearby?lat=&lon=&dist=     aircraft in an area
GET  /api/aircraft?reg=              where is this airframe right now
```

## Why hysteresis is the load-bearing detail

Real ADS-B drops the ground bit for a sample or two while an aircraft is still
on the taxiway. A naive state machine turns each flicker into a "Departed" push.
Air/ground transitions here require two consecutive consistent samples before
they become an event — and three tests exist purely to hold that line, because
the only thing this kind of product sells is that its alerts are trustworthy.
