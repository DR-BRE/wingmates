# Wingmates — your flight history on a globe, with your mates

Three things in one app, sharing one map:

- **My flights** — log the flights you've taken (by hand or CSV) and see them
  as arcs on a 3D globe, with totals for flights, miles, airports and countries.
- **Social** — find people by username, become mates, and compare wingspans.
- **Live** — track a real aircraft right now from ADS-B data, with a state
  machine that derives departure/landing/descent and an alert feed.

No API key and no account. The browser loads its map libraries and textures
from public CDNs, so it needs an internet connection.

```
cd wingmates
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py
```

Opens `http://127.0.0.1:8817`. Press `ctrl-c` to stop. Needs Python 3.11+.

```
.venv/bin/python run.py --port 9000     # different port
.venv/bin/python run.py --no-browser    # don't auto-open
.venv/bin/python -m unittest discover -s tests -t .   # offline tests
```

By default there is no sign-in: on your own machine every request acts as one
local user, `@you`. To have people sign in with Google, see
[docs/google-sign-in-setup.md](docs/google-sign-in-setup.md).

To put it on the internet for friends, free, see
[docs/deploy-vercel.md](docs/deploy-vercel.md). A paid alternative is in
[docs/deploy-render.md](docs/deploy-render.md).

### Settings

| Variable | Default | Effect |
|---|---|---|
| `WINGMATES_LIVE` | `1` | `0` turns off the live tracker and hides the Live tab. |
| `WINGMATES_DEV_USERS` | `0` | `1` adds a box in the header to switch between made-up users, for trying the Social tab. Never enable this on a server others can reach. |
| `WINGMATES_DATA_DIR` | `~/.wingmates` | Where `flights.db` and `state.json` live. |
| `WINGMATES_AUTH` | `local` | `google` requires sign-in. Live then defaults to off and dev users are ignored. |
| `WINGMATES_BASE_URL` | `http://localhost:8817` | The address people use. Google returns sign-ins here, and the app only answers to this host and the local names. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | from `~/.wingmates/google-client.json` | The Google client, when not using the downloaded file. |
| `SECRET_KEY` | generated, kept in `~/.wingmates/secret_key` | Signs session cookies. |
| `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` | unset | Keep the data in a Turso database instead of the local file. `SECRET_KEY` is then required. |
| `WINGMATES_USE_TURSO` | `0` | `1` uses the Turso settings saved in `~/.wingmates/turso.json`, for trying Turso from your own machine. |

## My flights

Everything here is stored locally in `~/.wingmates/flights.db` (SQLite).

| | |
|---|---|
| **Add a flight** | From, To and a date are all that's required. Codes can be IATA (`ATL`) or ICAO (`KATL`); typing a city name suggests airports. Airline, flight number, aircraft, seat and notes are optional. After each add, *From* is pre-filled with where you just landed, so connecting legs go quickly. |
| **Import / export CSV** | Download the template from the app, fill it in, import it. Bad rows are reported by line number while the good ones still go in. Importing the same file twice adds nothing. Export downloads all your flights in the same columns. |
| **Edit / delete** | ✎ loads a flight back into the form and saving recomputes the distance. Delete takes two clicks so a stray tap can't lose a flight. |
| **Totals** | Flights, great-circle miles, distinct airports, distinct countries. |
| **Routes** | One arc per airport pair on both the globe and the flat map. Click a flight in the list to frame it. |

### CSV format

```
date,from,to,airline,flight_number,aircraft,seat,notes
2024-03-09,ATL,LHR,Delta,DL30,A333,34A,window
```

`date`, `from` and `to` are required; dates are `YYYY-MM-DD`. Common header
spellings also work (`Origin`, `Destination`, `Carrier`, `Flight No`, …), and a
byte-order mark from Excel is handled. Two rows with the same date, route and
flight number count as the same flight; the same route and day with *different*
flight numbers are kept as two flights.

## Social

| | |
|---|---|
| **Find a mate** | Type someone's exact username. There is no browsing or partial search. |
| **Requests** | Adding someone sends a request they accept or decline. Declining is silent. |
| **Wingspan** | Total great-circle miles flown, also shown as times around the Earth. Mates are ranked by it. |
| **Head to head** | Click a mate to compare wingspan, flights, airports and countries, and to draw their routes on the globe in coral beside yours. |

A mate sees your totals and your distinct routes. They never see dates,
airlines, flight numbers, seats, notes, or how often you flew a route.

## The globe

A sphere displaced by real elevation data, shaded dark: near-black oceans, slate
terrain lit by relief, teal coastline glow, amber city lights, an atmosphere
halo and stars. Terrain height is exaggerated for the sculpted look. Drag to
rotate, scroll or pinch to zoom, and use the **Globe / Map** toggle for the
flat map. If WebGL or the CDN is unavailable, the app stays on the flat map.

It is built from free textures (NASA-derived, shipped with the MIT-licensed
[three-globe](https://github.com/vasturiano/three-globe) package) rather than a
purchased 3D model, so there is no model licence to manage. Close-up detail is
limited by the 2048-px elevation map.

## Live tracking

| | |
|---|---|
| **Track a flight** | By ADS-B callsign (`DAL983`, `BAW117`). Resolves against the live feed immediately — no spinner, no fake "pending" state. |
| **Live map** | Aircraft rotated to true track, with position trails that accumulate as it flies. |
| **Phase detection** | At gate → pushback → taxi → airborne (climb/cruise/descent) → landed → taxi in → at gate. Derived entirely from position reports. |
| **Alerts** | Departed, Landed, Descent started, Reached cruise, Pushed back, At the gate, altitude milestones. Loud events toast on screen. |
| **Emergency squawks** | 7500/7600/7700 detected and escalated on the *first* sample, no hysteresis delay. |
| **Where's my plane** | Look up an airframe by registration (`G-RUKB`) and see what it's flying as right now. |
| **Nearby radar** | Every aircraft within about 90 nm of the view centre (wider when zoomed out on the globe, capped at 250 nm), one click to track any of them. |
| **Flight log** | Completed live-tracked flights with max altitude, max speed, duration. |
| **Survives restart** | Tracked flights and the alert feed persist to `~/.wingmates/state.json`, written atomically. |

Live-tracked flights and **My flights** are separate: tracking a flight does not
add it to your history.

## Data sources

| | Role | Gives |
|---|---|---|
| [adsb.lol](https://adsb.lol) | live, primary | callsign, registration, type, altitude, speed, vertical rate, track, squawk |
| [OpenSky](https://opensky-network.org) | live, fallback | position, altitude, speed, track (no registration or type) |
| [OurAirports](https://ourairports.com/data/) | history | ~8,800 airports with an IATA code, in `data/airports.csv` (public domain) |
| [Esri](https://www.arcgis.com) dark gray tiles | flat map | basemap and labels |

The flat map uses Esri because CARTO's free dark tiles now require an API key.
Esri's free tile terms suit a personal tool; check them again before opening
the app to many users.

Live failover is automatic and was **exercised for real during development**:
adsb.lol returned HTTP 429, the tracker switched to OpenSky mid-session, and
tracked flights kept updating. The status pill in the header always shows which
feed is live. A 429 triggers a 5-minute cooldown, because a free community feed
saying "slow down" deserves to be listened to.

Polling is deliberately gentle: one sweep every 20 s, 2 s between per-flight
calls, 12 tracked flights maximum — roughly 0.1 requests/second.

## What it deliberately cannot do

This is the honest part. **Everything Flighty sells that isn't position data
requires a paid feed**, and no amount of code substitutes for it:

- **Gates, terminals, baggage claim** — airline/GDS feeds, not ADS-B.
- **Scheduled times**, and therefore **delays**. Without a schedule there is no
  "late" — only "where the aircraft is". History entries are a date and two
  airports, with no departure or arrival times.
- **Cancellations** — a cancelled flight simply never appears on ADS-B, which is
  indistinguishable from an aircraft out of receiver coverage.
- **Codeshares** — ADS-B carries the operating callsign only, so a passenger
  booked on a marketing number has to know the operating one.
- **Push notifications to a phone** — alerts are in-app; real push needs an
  Apple Developer account and APNs.
- **Coverage gaps** — oceanic, polar, and much of Africa/Asia have thin or no
  community receiver coverage. Aircraft genuinely vanish there.
- **Airports without an IATA code** — small fields and heliports can't be
  entered in the history.

Flighty solves these with FlightAware Firehose plus schedule feeds, which is
enterprise-contract territory. The architecture here keeps that swap cheap: all
vendor field names stop inside `fc/adsb.py`, so adding a schedule provider means
a new client module and a wider `Position`, not a rewrite.

## Not built yet

Importing from calendar events or email confirmations, blocking and
reporting, and a custom domain.

## Layout

```
run.py                  entry point — starts poller + server
fc/schema.py            FlightKey, Position, Phase, Event, FlightState
fc/adsb.py              feed clients + automatic failover
fc/statemachine.py      phase detection with hysteresis
fc/tracker.py           poll loop, registry, alert feed, persistence
fc/airports.py          airport lookup by code, city or name
fc/history.py           flight history: SQLite store, CSV import, stats
fc/config.py            settings from environment variables
fc/db.py                SQLite schema and migration
fc/users.py             user records and username rules
fc/mates.py             mate requests, pairs, and what a mate may see
fc/auth.py              Google sign-in
fc/webapp.py            Flask app: every HTTP route
fc/hosted.py, wsgi.py   the app as a hosted server runs it (gunicorn)
Dockerfile, render.yaml the container and the Render service
web/                    HTML pages: the app, sign-in, choose-a-username
public/static/app.js    live tracker UI and the flat map (Leaflet)
public/static/history.js   My flights UI: form, list, edit, route drawing
public/static/social.js    Social tab
public/static/globe.js  3D globe (three.js), loaded as an ES module
public/static/style.css styles
wsgi.py                 entry point for Vercel
fc/turso.py             Turso client: SQL over HTTP, shaped like sqlite3
requirements.txt        Flask, Authlib, requests, gunicorn
data/airports.csv       airport table (OurAirports, public domain)
tests/                  offline tests — no network required
```

## API

```
GET  /api/state                      live: flights, alerts, log, status
POST /api/track      {callsign}      live: start tracking
POST /api/untrack    {key}           live: stop, and archive to the log
POST /api/poll                       live: force a feed poll now
GET  /api/nearby?lat=&lon=&dist=     live: aircraft in an area
GET  /api/aircraft?reg=              live: where is this airframe right now

GET  /auth/login, /auth/callback     Google sign-in            (google mode)
POST /auth/logout                    sign out                  (google mode)
POST /api/username {username}        choose a username, once   (google mode)
POST /api/account/delete {confirm}   delete your account       (google mode)
GET  /healthz                        health check for the host
GET  /api/me                         the current user and feature flags
GET  /api/history/export.csv         your flights as CSV
GET  /api/social                     you, your mates with stats, pending requests
GET  /api/users/lookup?username=     one person's card
POST /api/mates/request {username}   send a request
POST /api/mates/<id>/accept | decline | cancel | remove
GET  /api/mates/<id>/routes          one mate's distinct routes

GET  /api/history                    flights (newest first) and totals
POST /api/history    {date, from, to, airline?, flight_number?,
                      aircraft?, seat?, notes?}        add a flight
POST /api/history/update  {id, ...same fields}         replace a flight
POST /api/history/delete  {id}                         delete a flight
POST /api/history/import  {csv}                        import CSV text
GET  /api/history/template.csv       the import template
GET  /api/airports?q=                airport suggestions
```

## Why hysteresis is the load-bearing detail

Real ADS-B drops the ground bit for a sample or two while an aircraft is still
on the taxiway. A naive state machine turns each flicker into a "Departed" push.
Air/ground transitions here require two consecutive consistent samples before
they become an event — and three tests exist purely to hold that line, because
the only thing this kind of product sells is that its alerts are trustworthy.
