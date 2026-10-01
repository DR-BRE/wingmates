# Social page, mates and wingspans — design

Date: 2026-10-01 (revised the same day: invite links replaced by username lookup)
Status: awaiting review

## Goal

Let friends use Wingmates together: sign in with one tap, pick a username,
find each other by username on a Social page, and compare wingspans.

Today the app is one person on one laptop. This release makes it a hosted,
multi-user app while keeping the laptop workflow working.

**Done means:** two people sign in to the same hosted site and each picks a
username. One looks up the other's username and sends a request; the other
accepts. Each then sees the other on their Social page with both wingspans,
and can draw the other's routes on the globe. At no point does either receive
the other's flight dates, airlines, flight numbers, seats or notes.

## Decisions already made

| Question | Decision |
|---|---|
| Sign-in | A "Continue with Google" button. No passwords are stored. |
| Identity inside the app | A username chosen at first sign-in. |
| Finding people | Look up an exact username on the Social page. No invite links. |
| Becoming mates | A request the other person accepts. |
| First release | Sign-in, Social page, wingspans. Flights are added by manual entry and CSV. |
| What a mate sees | Totals and distinct routes. No dates or per-flight details. |
| Wingspan | Total great-circle miles flown. |
| Server | Flask, with Authlib for Google sign-in. |
| Storage | SQLite on the host's persistent disk. |

Because people are found by username and there are no invites, **anyone who
finds the site can create an account.** Request-and-accept is what stops a
stranger from seeing someone's routes.

## Out of scope

- Importing flights from Gmail, Calendar or forwarded email. Before designing
  it, confirm Google's current rules: Gmail read access is believed to be a
  restricted scope needing verification and a paid security assessment.
- Browsing or searching users by partial name. Lookup is exact username only.
- Changing a username after it is chosen.
- Blocking and reporting, beyond the decline rule described below.
- Notifications of any kind. Requests are seen when the Social page is opened.
- Live tracking on the hosted site (see Modes).
- Per-flight privacy controls, such as hiding one route from mates.
- Postgres, multiple server instances, a native app.

## Modes

Two settings, read from environment variables, decide how the app behaves.

| Setting | Values | Default | Effect |
|---|---|---|---|
| `WINGMATES_AUTH` | `local`, `google` | `local` | `local`: no sign-in, every request acts as the local user. `google`: sign-in required. |
| `WINGMATES_LIVE` | `1`, `0` | `1` when auth is `local`, else `0` | Whether the live tracker runs and the Live tab and its endpoints exist. |
| `WINGMATES_DEV_USERS` | `1`, `0` | `0` | Only honoured when auth is `local`. Adds a control to switch between made-up users, for testing the Social page without Google. |
| `WINGMATES_DATA_DIR` | path | `~/.wingmates` | Where the database and tracker state live. |
| `WINGMATES_BASE_URL` | URL | `http://localhost:8817` | Used to build the Google redirect address. Cookies are marked Secure when it starts with `https`. |
| `SECRET_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | secrets | none | Required when auth is `google`. The app refuses to start without them. |

`python3 run.py` with nothing set behaves as it does today: one local user,
Live tab present. It now needs `pip install -r requirements.txt` once.

Live is off on the hosted site because it polls free community feeds, one of
which (OpenSky) is licensed for non-commercial use, and because the tracker
holds one shared list of flights rather than one per user.

## Architecture

```
run.py              starts the Flask app, and the tracker when Live is on
fc/config.py        reads the settings above into one Config object
fc/db.py            opens SQLite connections, creates and migrates the schema
fc/users.py         user records: create from Google profile, usernames, lookup, delete
fc/history.py       flight history, now scoped to a user id (existing file)
fc/mates.py         requests, mate pairs, and what one person may see of another
fc/auth.py          Google sign-in, sessions, the signed-in-user check
fc/webapp.py        Flask app factory and every route
fc/airports.py      unchanged
fc/tracker.py, adsb.py, statemachine.py, schema.py   unchanged
fc/server.py        removed; webapp.py replaces it
web/login.html      sign-in page
web/welcome.html    choose-a-username page
web/social.js       Social tab
web/globe.js        gains a second route layer for a mate's routes
```

Each store (`users`, `history`, `mates`) takes a database path and knows
nothing about HTTP. `webapp.py` is the only file that knows about requests,
and `auth.py` is the only file that knows about Google. This keeps the stores
testable with a temp database and no web client.

Dependencies, pinned in `requirements.txt`: Flask, Authlib, requests (needed
by Authlib), gunicorn (hosted only).

## Data

One SQLite file, `flights.db`, in the data directory. Foreign keys are on.
The schema version is stored in `PRAGMA user_version`.

```
users
  id           INTEGER PRIMARY KEY AUTOINCREMENT   -- ids are never reused
  google_sub   TEXT UNIQUE          -- Google's stable account id; NULL for local users
  username     TEXT UNIQUE          -- lowercase; NULL until chosen
  email        TEXT
  name         TEXT NOT NULL
  picture_url  TEXT
  created_at   TEXT NOT NULL

flights                              -- existing table, plus:
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
  index on (user_id, date)

mate_requests
  from_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
  to_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
  status       TEXT NOT NULL         -- 'pending', 'declined' or 'withdrawn'
  created_at   TEXT NOT NULL
  PRIMARY KEY (from_id, to_id), CHECK (from_id != to_id)

mates
  user_lo      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
  user_hi      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
  created_at   TEXT NOT NULL
  PRIMARY KEY (user_lo, user_hi), CHECK (user_lo < user_hi)
```

A mate pair is stored once, smaller id first, so the relationship is mutual by
construction and cannot be half-added.

User ids are never reused. Otherwise a session cookie left over from a deleted
account could open a newer account that was given the same id.

### Usernames

- 3 to 20 characters: lowercase letters, digits and underscore. Input is
  lowercased before checking, so `Brett` and `brett` are the same username.
- Unique across all users. Shown everywhere with an `@` in front.
- A short list of reserved words (`admin`, `wingmates`, `support`, `you`) is
  refused, to prevent impersonating the app.
- Chosen once and not changeable in this release.

### Migration from today's database

On first start, if `flights` has no `user_id` column: create the new tables,
insert one local user named "You" with username `you`, add the column, and
assign every existing flight to that user. The existing tests' fixtures start
from an empty database and are unaffected.

### Moving local flights to the hosted site

The local user is not a Google account and is never merged with one. To move
flights, the person uses a new **Export CSV** button locally and **Import CSV**
on the hosted site. The export uses the same columns as the import template, so
it round-trips.

## Wingspan and stats

- **Wingspan** is the sum of the great-circle distance of every flight the
  user has logged, in statute miles, rounded to a whole mile.
- **Times around the Earth** is wingspan divided by 24,901, shown to one
  decimal place.
- The other compared stats are flight count, distinct airports and distinct
  countries, computed as they are today.

## What one person may see of another

`fc/mates.py` is the only code that produces data about another user, and it
builds that data from explicit lists of allowed fields.

**Anyone signed in, by looking up an exact username,** receives only:

- `id`, `username`, `name`, `picture_url`
- `relation`: one of `self`, `mate`, `requested` (you asked them), `incoming`
  (they asked you), `none`

Name and picture are shown so a person can check they found the right
account before sending a request. No stats and no routes.

**A mate** additionally receives:

- `stats`: `flights`, `distance_mi`, `distance_km`, `airports`, `countries`
- `routes`: one entry per distinct airport pair regardless of direction, each
  with both airports' code, name, city, country and coordinates

**Nobody but the owner** ever receives: email, flight dates, airlines, flight
numbers, aircraft, seats, notes, flight ids, or how many times a route was
flown.

Asking for the routes of someone who is not your mate returns 404, the same
answer as for a user who does not exist.

## Sign-in, username and sessions

- Google sign-in uses the OpenID Connect authorization-code flow through
  Authlib, with scopes `openid email profile` only. Authlib handles the
  `state` and `nonce` checks.
- A user is identified by Google's `sub` value, not by email, so a changed
  email address does not create a second account. Name, email and picture are
  refreshed on each sign-in.
- **First sign-in:** the account has no username yet. Every page redirects to
  the welcome page, and every `/api/` route except `/api/me` and
  `/api/username` answers 409, until a username is chosen. A taken, reserved
  or badly formed username is refused with a message saying which.
- The session is Flask's signed cookie holding only the user id. It is
  HttpOnly, SameSite=Lax, Secure when the base URL is https, and lasts 30
  days.
- Every `/api/` route requires a signed-in user and answers 401 otherwise,
  including `/api/me`, which the page uses to find out whether it is signed
  in. Pages redirect to the sign-in page instead.
- After sign-in the user returns to the page they wanted. The return address
  is accepted only if it is a path on this site.
- Requests that change data must be `POST` with a JSON body and an `Origin`
  header naming the same host and port the request was sent to. Others are
  rejected with 403. Comparing against the request's own host, not the
  configured base URL, keeps `localhost` and `127.0.0.1` both working
  locally. Sign-out is a `POST`.

## Requests and mates

1. On the Social page a user types a username and presses **Find**.
2. If that exact username exists, a card shows the person's picture, name and
   username with an **Add mate** button. If not, it says no one has that
   username.
3. **Add mate** creates a pending request. The card changes to "Requested",
   with a **Cancel** action.
4. The other person sees the request under **Requests** on their Social page,
   with **Accept** and **Decline**.
5. **Accept** stores the mate pair and deletes the request. Both people now
   appear in each other's mates list.

| Situation | Result |
|---|---|
| Looking up your own username | The card says this is you. No button. |
| Already mates | The card says so. No button. |
| They already sent you a request | The card offers **Accept** instead of Add mate. |
| You add someone who has a pending request to you | Treated as accepting it: you become mates at once. |
| You decline | The request is kept, marked declined. The sender still sees "Requested" and is not told. They cannot send another. You can still add them yourself later, which makes you mates. |
| You cancel a request you sent | If it was still pending it is deleted, and you may send a new one later. If it had been declined it is marked withdrawn: it disappears from your list, but a new request from you still does not reach them. |
| A user sends many requests | No more than 20 requests showing as "Requested" per user; further ones are refused with a message. |

Either mate can **remove** the other from the Social page. Removal deletes
the pair for both and leaves no request behind, so either can send a new
request afterwards.

## Deleting an account

**Delete account** is in the account menu. It requires typing `DELETE`. It
removes the user row, and the database cascades that to their flights,
requests and mate pairs. The username becomes available again. The session is
then cleared. It cannot be undone, and the dialog says so.

## HTTP API

Existing history routes keep their paths and shapes and become scoped to the
signed-in user. Live routes exist only when Live is on.

```
GET  /auth/login                     redirect to Google (google auth only)
GET  /auth/callback                  finish sign-in, set the session
POST /auth/logout                    clear the session
GET  /api/me                         the signed-in user and feature flags
POST /api/username  {username}       choose a username (first sign-in only)

GET  /api/history                    my flights and totals
POST /api/history                    add
POST /api/history/update             replace one of my flights
POST /api/history/delete             delete one of my flights
POST /api/history/import             import CSV text
GET  /api/history/export.csv         my flights as CSV          (new)
GET  /api/history/template.csv
GET  /api/airports?q=

GET  /api/social                     me, my mates with stats by wingspan,
                                     incoming and outgoing pending requests
GET  /api/users/lookup?username=     one person's card, or 404
POST /api/mates/request  {username}  send a request
POST /api/mates/<id>/accept          accept their request
POST /api/mates/<id>/decline         decline their request
POST /api/mates/<id>/cancel          cancel my request to them
POST /api/mates/<id>/remove          stop being mates
GET  /api/mates/<id>/routes          one mate's distinct routes
POST /api/account/delete {confirm}

GET  /healthz                        for the host's health check
POST /dev/login  {username}          switch user (dev users only)
```

Updating or deleting a flight id that belongs to someone else answers exactly
as it does for an id that does not exist.

## Front end

- **Signed out:** `login.html`, a single **Continue with Google** button.
- **First sign-in:** `welcome.html`, one field to choose a username, checked
  as it is submitted.
- **Header:** the user's picture and `@username`, with a menu holding Sign out
  and Delete account. In local mode the menu is replaced by the dev user
  switcher when that is enabled, and is otherwise absent.
- **Tabs:** My flights, Social, and Live when it is on.
- **My flights:** as today, plus an Export CSV link beside Template.
- **Social tab,** top to bottom:
  - **Find a mate:** a username field and Find button, with the result card
    below it.
  - **Requests:** incoming requests with Accept and Decline, then requests the
    user has sent with Cancel. Hidden when there are none. The tab label shows
    a count when there are incoming requests.
  - **Mates:** the user and their mates ranked by wingspan. Each row has
    picture, name, `@username`, miles, times around the Earth, countries and
    airports. The user's own row is marked.
  - Clicking a mate opens a head-to-head panel: four rows (wingspan, flights,
    airports, countries) with the leader of each highlighted, and a Remove
    button. The mate's routes are drawn on the globe and flat map in a second
    colour alongside the user's own. Clicking the mate again, or another tab,
    clears them.
  - With no mates yet, the list shows only the user's own wingspan, with a
    line pointing at Find a mate.
- **Globe and map:** `Globe3D.setRoutes` stays for the user's routes. A new
  `setMateRoutes(routes, airports)` draws a second layer in coral (`#f08a6b`),
  distinct from the teal used for the user and the amber used for city lights.

## Escaping

Names, usernames and pictures now come from other people, so every value
placed in the page must be escaped. `web/history.js` already does this. The
Live code in `web/app.js` does not: callsigns and registrations are inserted
into `innerHTML`, and into inline `onclick` attributes at two places. Those
are rewritten to use escaped text and attached click handlers. Picture URLs
are only used as `img src` and only when they start with `https://`.

## Hosting

- A `Dockerfile` runs gunicorn with one worker process and several threads.
  One process is required: SQLite on a local disk does not support several
  servers writing at once.
- The data directory is a persistent disk mounted into the container. Without
  one, every deploy would erase all accounts and flights, so the host must
  offer persistent storage. This rules out free tiers that have none.
- HTTPS is provided by the host. Secrets are set as host environment
  variables and never committed.
- Backups: the host's disk snapshots, to be switched on at deploy time. Each
  user can also export their own flights as CSV.
- The specific host is chosen at the deploy step, after checking current
  pricing and storage options.

## Build order

Each step ends with something that can be tried.

1. **Multi-user core, local.** Flask replaces the built-in server. Users,
   usernames, scoped flights, migration, requests, mates, the Social tab, CSV
   export, the escaping fixes, and the dev user switcher. Two made-up users
   can find each other by username, become mates and compare wingspans on
   localhost.
2. **Google sign-in.** `auth.py`, the sign-in and welcome pages, sessions,
   account deletion. Works on localhost with a Google OAuth client. Includes a
   short setup guide, `docs/google-sign-in-setup.md`.
3. **Deploy.** Dockerfile, health check, host configuration, a deploy guide.

Steps 2 and 3 each need something only the owner can do: create the Google
Cloud OAuth client, and create the hosting account.

## Tests

Existing tests keep passing; `History` tests gain a user id.

New tests, all offline, using a temp database and Flask's test client:

- **Isolation.** User A cannot list, update or delete user B's flights; the
  answers match those for a missing id. Stats count only the user's own
  flights. CSV import and its duplicate check are per user.
- **Migration.** A database in today's format gains a local user that owns
  every existing flight.
- **Usernames.** Case is folded. Too short, too long, bad characters, reserved
  and taken names are each refused. A username cannot be set twice. A deleted
  account's username can be taken again.
- **Lookup.** An exact match returns only the card fields. A partial or
  unknown username gives 404. `relation` is correct in each of the five
  states.
- **Requests.** Request then accept makes a pair visible from both sides.
  Crossing requests make a pair at once. Decline blocks a second request from
  the same sender, hides nothing from them, and still lets the decliner add
  them. Cancel allows a later re-request. Requesting yourself, a mate, or
  beyond the limit of 20 is refused.
- **Mates.** Removal by either side removes the pair for both and allows a new
  request. Deleting an account removes its flights, requests and pairs.
- **Privacy.** The social, lookup and routes responses contain exactly the
  allowed field names. A route flown five times appears once. Routes of a
  non-mate, of a pending-request user and of a missing user all give 404.
- **Auth.** Every `/api/` route gives 401 when signed out. With no username
  yet, routes other than `/api/me` and `/api/username` give 409. A `POST` with
  a foreign or missing `Origin` gives 403. The post-sign-in return address
  rejects anything that is not a local path. Google itself is not called in
  tests; the callback is tested with a stubbed profile.
- **Modes.** With Live off, live routes give 404. With `google` auth and a
  missing secret, the app refuses to start. `/dev/login` gives 404 unless dev
  users are enabled in local auth.
- **Export.** Exported CSV imports back to the same flights.

## Risks

- **Open sign-up.** Anyone can create an account and send requests to
  usernames they know or guess. Mitigations: routes are visible only after
  acceptance, a declined sender cannot ask again, and outgoing requests are
  capped. There is no blocking or reporting yet; add them before the site is
  shared beyond friends of friends.
- **Impersonation by username.** Someone could register a friend's usual
  handle first. Mitigation: the lookup card shows the Google name and picture
  so a request can be checked before it is sent or accepted.
- **One SQLite file on one disk** is a single point of failure. Acceptable for
  a friend group with snapshots on; revisit before growing beyond that.
- **Google consent screen.** Basic sign-in scopes are believed to need no
  Google review. Confirm this while doing step 2.
- **Esri map tiles** and the community flight feeds have usage terms written
  for personal use. Recheck both before inviting many people.
