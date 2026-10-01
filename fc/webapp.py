"""The Flask app: every HTTP route. The only module that knows about requests.

There is no real sign-in yet. Every request acts as the local user, unless
dev users are enabled and the session names another one.
"""
from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import urlsplit

from flask import (Flask, Response, g, jsonify, request, send_from_directory,
                   session)
from werkzeug.exceptions import HTTPException

from .adsb import FeedError
from .airports import Airports
from .config import Config
from .history import OPTIONAL, History, template_csv
from .mates import Mates
from .users import Users, normalize_username, validate_username

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def create_app(config: Config, tracker=None,
               airports: Airports | None = None) -> Flask:
    app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="/static")
    app.secret_key = config.secret_key or secrets.token_hex(32)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.base_url.startswith("https://"),
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )

    history = History(airports, config.db_path)
    users = Users(config.db_path)
    mates = Mates(users, history)

    # ------------------------------------------------------------- helpers
    def current_user() -> dict:
        if config.dev_users:
            uid = session.get("uid")
            user = users.get(uid) if uid else None
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

    def flight_fields(data: dict) -> dict:
        return {k: str(data.get(k) or "") for k in OPTIONAL}

    @app.errorhandler(ApiError)
    def api_error(e: ApiError):
        return jsonify(error=e.message), e.status

    @app.errorhandler(HTTPException)
    def http_error(e: HTTPException):
        if request.path.startswith(("/api/", "/dev/")):
            return jsonify(error=e.name.lower()), e.code
        return e

    @app.before_request
    def guard():
        if request.method == "POST":
            origin = urlsplit(request.headers.get("Origin", "")).netloc
            if not origin or origin != request.host:
                raise ApiError("cross-site request refused", 403)
            if not request.is_json:
                raise ApiError("requests must be JSON", 403)
        if request.path.startswith(("/api/", "/dev/")):
            g.user = current_user()

    @app.after_request
    def caching(resp: Response) -> Response:
        resp.headers["Cache-Control"] = (
            "no-store" if request.path.startswith("/api/") else "no-cache")
        return resp

    # --------------------------------------------------------------- pages
    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

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
            return jsonify(flights().add(data.get("date"), data.get("from"),
                                         data.get("to"), **flight_fields(data)))
        except ValueError as e:
            raise ApiError(str(e)) from None

    @app.post("/api/history/update")
    def history_update():
        data = body()
        try:
            fid = int(data.get("id"))
        except (TypeError, ValueError):
            raise ApiError("id is required") from None
        try:
            found = flights().update(fid, data.get("date"), data.get("from"),
                                     data.get("to"), **flight_fields(data))
        except ValueError as e:
            raise ApiError(str(e)) from None
        if found is None:
            raise ApiError("no such flight", 404)
        return jsonify(found)

    @app.post("/api/history/delete")
    def history_delete():
        try:
            fid = int(body().get("id"))
        except (TypeError, ValueError):
            raise ApiError("id is required") from None
        return jsonify(removed=flights().delete(fid))

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

    # ----------------------------------------------------------- dev users
    if config.dev_users:
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
