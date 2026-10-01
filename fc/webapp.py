"""The Flask app: every HTTP route. The only module that knows about requests.

Two auth modes. In `local` every request acts as the local user (or a made-up
one, when dev users are on). In `google` the session names the signed-in
account, and nothing under /api/ answers without one.
"""
from __future__ import annotations

import secrets
import sqlite3
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from flask import (Flask, Response, g, jsonify, redirect, request,
                   send_from_directory, session)
from werkzeug.exceptions import HTTPException

from .adsb import FeedError
from .airports import Airports
from .auth import GoogleSignIn, persistent_key, safe_next
from .config import Config
from .db import readable
from .history import OPTIONAL, History, template_csv
from .mates import Mates
from .users import Users, normalize_username, validate_username

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"                       # HTML pages, served by routes
STATIC_DIR = ROOT / "public" / "static"      # .js and .css, served at /static/

# The largest id SQLite can hold. Anything beyond it cannot name a row.
MAX_ID = 2 ** 63 - 1
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# The largest request accepted. A lifetime of flights as CSV is well under
# 100 KB; without a cap, one request could exhaust memory or the shared disk.
MAX_REQUEST_BYTES = 2 * 1024 * 1024
# Routes a signed-in person may use before choosing a username.
USERNAME_FREE = frozenset({"/api/me", "/api/username", "/api/account/delete"})


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def create_app(config: Config, tracker=None, airports: Airports | None = None,
               sign_in=None) -> Flask:
    google = config.auth == "google"
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    # Real accounts need a key that survives restarts, or everyone is signed
    # out each time. Local mode has nothing to keep.
    app.secret_key = config.secret_key or (
        persistent_key(config.data_dir) if google else secrets.token_hex(32))
    app.permanent_session_lifetime = timedelta(days=30)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.base_url.startswith("https://"),
        SEND_FILE_MAX_AGE_DEFAULT=0,
        MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
    )

    history = History(airports, config.database)
    users = Users(config.database)
    mates = Mates(users, history)
    if google and sign_in is None:
        sign_in = GoogleSignIn(app, config.google_client_id,
                               config.google_client_secret)
    base_host = urlsplit(config.base_url).netloc

    # ------------------------------------------------------------- helpers
    def current_user() -> dict | None:
        uid = session.get("uid")
        if google:
            return users.for_session(uid, session.get("epoch")) if uid else None
        if config.dev_users and uid:
            user = users.get(uid)
            if user:
                return user
        return users.ensure_local()

    def body() -> dict:
        data = request.get_json(silent=True)
        if data is None and not request.get_data():
            return {}
        if not isinstance(data, dict):
            raise ApiError("the request body must be a JSON object")
        return data

    def flights():
        return history.for_user(g.user["id"])

    def text(data: dict, key: str) -> str:
        value = data.get(key)
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ApiError(f"{key} must be text")
        return value

    def flight_args(data: dict) -> tuple:
        return (text(data, "date"), text(data, "from"), text(data, "to"))

    def flight_fields(data: dict) -> dict:
        return {k: text(data, k) for k in OPTIONAL}

    def flight_id(data: dict) -> int:
        """The id in a request body. An id too large to exist is returned as
        0, which matches no row, so it reads as missing rather than as an
        error."""
        value = data.get("id")
        # bool is an int in Python; `true` must not be read as flight 1.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError("id is required")
        return value if 0 < value <= MAX_ID else 0

    @app.errorhandler(ApiError)
    def api_error(e: ApiError):
        return jsonify(error=e.message), e.status

    @app.errorhandler(sqlite3.Error)
    def database_error(e: sqlite3.Error):
        # The type only: a database error's text can quote what was stored.
        app.logger.error("database error: %s", type(e).__name__)
        message = "the database is unavailable; please try again shortly"
        if request.path.startswith(("/api/", "/dev/")):
            return jsonify(error=message), 503
        return message.capitalize() + ".", 503

    @app.errorhandler(HTTPException)
    def http_error(e: HTTPException):
        if request.path.startswith(("/api/", "/dev/")):
            return jsonify(error=e.name.lower()), e.code
        return e

    # Hosts this app answers to. Without this, a web page whose domain is made
    # to resolve to 127.0.0.1 would count as same-origin and could read and
    # change the owner's flights.
    allowed_hosts = LOCAL_HOSTS | {urlsplit(config.base_url).hostname}

    @app.before_request
    def guard():
        if request.path == "/healthz":
            # The host's health checker calls from inside its own network,
            # under a name this app does not know. The route reveals nothing.
            return None
        if urlsplit("//" + request.host).hostname not in allowed_hosts:
            raise ApiError("unknown host", 403)
        if (google and request.method == "GET" and request.host.lower() != base_host
                and not request.path.startswith(("/api/", "/static/"))):
            # Google returns people to the configured address, and cookies do
            # not carry between localhost and 127.0.0.1, so pages move there
            # before sign-in starts.
            return redirect(config.base_url + request.full_path.rstrip("?"))
        if request.method == "POST":
            origin = urlsplit(request.headers.get("Origin", "")).netloc
            if not origin or origin != request.host:
                raise ApiError("cross-site request refused", 403)
            if not request.is_json:
                raise ApiError("requests must be JSON", 403)
        if request.path.startswith("/static/"):
            return None
        g.user = current_user()
        if request.path.startswith(("/api/", "/dev/")):
            if g.user is None:
                raise ApiError("sign in required", 401)
            if g.user["username"] is None and request.path not in USERNAME_FREE:
                raise ApiError("choose a username first", 409)
        return None

    @app.after_request
    def caching(resp: Response) -> Response:
        resp.headers["Cache-Control"] = (
            "no-store" if request.path.startswith("/api/") else "no-cache")
        return resp

    # --------------------------------------------------------------- pages
    @app.get("/healthz")
    def healthz():
        """Can the database be read? Asking never creates a missing file."""
        if not readable(config.database):
            return jsonify(ok=False), 503
        return jsonify(ok=True)

    @app.get("/")
    def index():
        if google and g.user is None:
            return redirect("/login")
        if google and g.user["username"] is None:
            return redirect("/welcome")
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/login")
    def login_page():
        if not google or g.user is not None:
            return redirect("/")
        return send_from_directory(WEB_DIR, "login.html")

    @app.get("/welcome")
    def welcome_page():
        if not google:
            return redirect("/")
        if g.user is None:
            return redirect("/login")
        if g.user["username"] is not None:
            return redirect("/")
        return send_from_directory(WEB_DIR, "welcome.html")

    @app.get("/api/me")
    def me():
        return jsonify({**g.user, "auth": config.auth,
                        "live": tracker is not None,
                        "dev_users": config.dev_users})

    # ------------------------------------------------------------- history
    @app.get("/api/history")
    def history_list():
        return jsonify(flights().snapshot())

    @app.post("/api/history")
    def history_add():
        data = body()
        try:
            return jsonify(flights().add(*flight_args(data),
                                         **flight_fields(data)))
        except ValueError as e:
            raise ApiError(str(e)) from None

    @app.post("/api/history/update")
    def history_update():
        data = body()
        fid = flight_id(data)
        try:
            found = flights().update(fid, *flight_args(data),
                                     **flight_fields(data))
        except ValueError as e:
            raise ApiError(str(e)) from None
        if found is None:
            raise ApiError("no such flight", 404)
        return jsonify(found)

    @app.post("/api/history/delete")
    def history_delete():
        return jsonify(removed=flights().delete(flight_id(body())))

    @app.post("/api/history/import")
    def history_import():
        text = body().get("csv")
        if not isinstance(text, str) or not text.strip():
            raise ApiError("csv is required")
        try:
            return jsonify(flights().import_csv(text))
        except ValueError as e:
            raise ApiError(str(e)) from None

    def _csv(text: str, filename: str) -> Response:
        return Response(text, mimetype="text/csv", headers={
            "Content-Disposition": f'attachment; filename="{filename}"'})

    @app.get("/api/history/export.csv")
    def history_export():
        return _csv(flights().export_csv(), "wingmates-flights.csv")

    @app.get("/api/history/template.csv")
    def history_template():
        return _csv(template_csv(), "flights-template.csv")

    @app.get("/api/airports")
    def airport_search():
        found = history.airports.search(request.args.get("q", ""))
        return jsonify(airports=[a.to_json() for a in found])

    # -------------------------------------------------------------- social
    @app.get("/api/social")
    def social():
        return jsonify(mates.social(g.user["id"]))

    @app.get("/api/users/lookup")
    def lookup():
        card = mates.card(g.user["id"], request.args.get("username", ""))
        if card is None:
            raise ApiError("no one has that username", 404)
        return jsonify(card)

    @app.post("/api/mates/request")
    def mate_request():
        try:
            return jsonify(mates.request(g.user["id"],
                                         str(body().get("username") or "")))
        except LookupError as e:
            raise ApiError(str(e), 404) from None
        except ValueError as e:
            raise ApiError(str(e)) from None

    def _mate_action(action, other_id: int, missing: str):
        if not action(g.user["id"], other_id):
            raise ApiError(missing, 404)
        return jsonify(ok=True)

    @app.post("/api/mates/<int(max=9223372036854775807):other_id>/accept")
    def mate_accept(other_id: int):
        return _mate_action(mates.accept, other_id, "no such request")

    @app.post("/api/mates/<int(max=9223372036854775807):other_id>/decline")
    def mate_decline(other_id: int):
        return _mate_action(mates.decline, other_id, "no such request")

    @app.post("/api/mates/<int(max=9223372036854775807):other_id>/cancel")
    def mate_cancel(other_id: int):
        return _mate_action(mates.cancel, other_id, "no such request")

    @app.post("/api/mates/<int(max=9223372036854775807):other_id>/remove")
    def mate_remove(other_id: int):
        return _mate_action(mates.remove, other_id, "not found")

    @app.get("/api/mates/<int(max=9223372036854775807):other_id>/routes")
    def mate_routes(other_id: int):
        routes = mates.routes(g.user["id"], other_id)
        if routes is None:
            raise ApiError("not found", 404)
        return jsonify(routes=routes)

    # ------------------------------------------------------------- sign-in
    if google:
        @app.get("/auth/login")
        def auth_login():
            # Each attempt leaves a state entry in the cookie. Clear the old
            # ones, or enough abandoned attempts would outgrow the cookie.
            for key in [k for k in session if k.startswith("_state_")]:
                session.pop(key)
            session["next"] = safe_next(request.args.get("next"))
            try:
                return sign_in.begin(config.base_url + "/auth/callback")
            except Exception as e:                    # noqa: BLE001
                app.logger.warning("could not start Google sign-in: %s",
                                   type(e).__name__)
                return redirect("/login?error=1")

        @app.get("/auth/callback")
        def auth_callback():
            profile = sign_in.finish()
            if profile is None:
                return redirect("/login?error=1")
            user = users.upsert_google(**profile)
            target = safe_next(session.get("next"))
            # Start a clean session: nothing from before sign-in carries over.
            session.clear()
            session["uid"] = user["id"]
            session["epoch"] = users.session_epoch(user["id"])
            session.permanent = True
            return redirect(target)

        @app.post("/auth/logout")
        def auth_logout():
            # Ends every session of the account, not only this browser's.
            if g.user is not None:
                users.end_sessions(g.user["id"])
            session.clear()
            return jsonify(ok=True)

        @app.post("/api/username")
        def choose_username():
            try:
                return jsonify(users.set_username(g.user["id"],
                                                  body().get("username")))
            except ValueError as e:
                raise ApiError(str(e)) from None

        @app.post("/api/account/delete")
        def account_delete():
            if body().get("confirm") != "DELETE":
                raise ApiError("type DELETE to confirm")
            users.delete(g.user["id"])
            session.clear()
            return jsonify(ok=True)

    # ----------------------------------------------------------- dev users
    # Never with sign-in on, whatever the Config says: this route lets the
    # caller become any user.
    if config.dev_users and not google:
        @app.post("/dev/login")
        def dev_login():
            raw = body().get("username")
            if normalize_username(raw) == "you":
                session.pop("uid", None)
                return jsonify(users.ensure_local())
            try:
                name = validate_username(raw)
            except ValueError as e:
                raise ApiError(str(e)) from None
            user = users.by_username(name) or users.create(name, name)
            session["uid"] = user["id"]
            return jsonify(user)

    # ---------------------------------------------------------------- live
    if tracker is not None:
        @app.get("/api/state")
        def live_state():
            return jsonify(tracker.snapshot())

        @app.post("/api/track")
        def live_track():
            cs = str(body().get("callsign") or "").strip()
            if not cs:
                raise ApiError("callsign is required")
            try:
                return jsonify(tracker.track(cs))
            except LookupError as e:
                raise ApiError(str(e), 404) from None
            except ValueError as e:
                raise ApiError(str(e)) from None

        @app.post("/api/untrack")
        def live_untrack():
            key = str(body().get("key") or "").strip()
            if not key:
                raise ApiError("key is required")
            return jsonify(removed=tracker.untrack(key))

        @app.post("/api/poll")
        def live_poll():
            return jsonify(updated=tracker.poll_once())

        @app.get("/api/nearby")
        def live_nearby():
            try:
                lat = float(request.args.get("lat", "33.64"))
                lon = float(request.args.get("lon", "-84.43"))
                dist = int(float(request.args.get("dist", "60")))
            except ValueError:
                raise ApiError("lat, lon and dist must be numbers") from None
            try:
                return jsonify(aircraft=tracker.nearby(lat, lon, dist))
            except FeedError as e:
                raise ApiError(f"feed unavailable: {e}", 503) from None

        @app.get("/api/aircraft")
        def live_aircraft():
            reg = request.args.get("reg", "").strip()
            if not reg:
                raise ApiError("reg is required")
            try:
                found = tracker.where_is_aircraft(reg)
            except FeedError as e:
                raise ApiError(f"feed unavailable: {e}", 503) from None
            if found is None:
                raise ApiError(f"{reg.upper()} is not transmitting right now", 404)
            return jsonify(found)

    return app
