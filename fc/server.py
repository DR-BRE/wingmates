"""HTTP API + static file serving. Stdlib only — no pip install required."""
from __future__ import annotations

import json
import mimetypes
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .adsb import FeedError
from .history import OPTIONAL, History, template_csv
from .tracker import Tracker

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class Handler(BaseHTTPRequestHandler):
    tracker: Tracker = None          # injected by serve()
    history: History = None
    server_version = "flighty-clone"

    def log_message(self, fmt, *args):
        pass                          # the tracker prints what matters

    # ------------------------------------------------------------- helpers
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, msg, status=400):
        self._json({"error": msg}, status)

    def _static(self, rel: str):
        # Resolve and confine to WEB_DIR — no traversal out of the web root.
        target = (WEB_DIR / rel).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
            self._err("not found", 404)
            return
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode())
        except json.JSONDecodeError:
            return {}

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        p = u.path
        t = self.tracker

        if p in ("/", "/index.html"):
            return self._static("index.html")
        if p.startswith("/static/"):
            return self._static(p[len("/static/"):])

        if p == "/api/state":
            return self._json(t.snapshot())

        if p == "/api/nearby":
            try:
                lat = float(q.get("lat", ["33.64"])[0])
                lon = float(q.get("lon", ["-84.43"])[0])
                dist = int(float(q.get("dist", ["60"])[0]))
            except ValueError:
                return self._err("lat, lon and dist must be numbers")
            try:
                return self._json({"aircraft": t.nearby(lat, lon, dist)})
            except FeedError as e:
                return self._err(f"feed unavailable: {e}", 503)

        if p == "/api/aircraft":
            reg = (q.get("reg", [""])[0] or "").strip()
            if not reg:
                return self._err("reg is required")
            try:
                found = t.where_is_aircraft(reg)
            except FeedError as e:
                return self._err(f"feed unavailable: {e}", 503)
            if found is None:
                return self._err(f"{reg.upper()} is not transmitting right now", 404)
            return self._json(found)

        if p == "/api/history":
            return self._json(self.history.snapshot())

        if p == "/api/history/template.csv":
            data = template_csv().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition",
                             'attachment; filename="flights-template.csv"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if p == "/api/airports":
            found = self.history.airports.search(q.get("q", [""])[0])
            return self._json({"airports": [a.to_json() for a in found]})

        return self._err("not found", 404)

    # ----------------------------------------------------------------- POST
    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        t = self.tracker
        body = self._body()

        if p == "/api/track":
            cs = (body.get("callsign") or "").strip()
            if not cs:
                return self._err("callsign is required")
            try:
                return self._json(t.track(cs))
            except LookupError as e:
                return self._err(str(e), 404)
            except ValueError as e:
                return self._err(str(e), 400)

        if p == "/api/untrack":
            key = (body.get("key") or "").strip()
            if not key:
                return self._err("key is required")
            return self._json({"removed": t.untrack(key)})

        if p == "/api/poll":
            return self._json({"updated": t.poll_once()})

        h = self.history
        if p == "/api/history":
            try:
                return self._json(h.add(
                    body.get("date"), body.get("from"), body.get("to"),
                    **{k: str(body.get(k) or "") for k in OPTIONAL}))
            except ValueError as e:
                return self._err(str(e))

        if p == "/api/history/update":
            try:
                fid = int(body.get("id"))
            except (TypeError, ValueError):
                return self._err("id is required")
            try:
                found = h.update(
                    fid, body.get("date"), body.get("from"), body.get("to"),
                    **{k: str(body.get(k) or "") for k in OPTIONAL})
            except ValueError as e:
                return self._err(str(e))
            return self._json(found) if found else self._err("no such flight", 404)

        if p == "/api/history/delete":
            try:
                return self._json({"removed": h.delete(int(body.get("id")))})
            except (TypeError, ValueError):
                return self._err("id is required")

        if p == "/api/history/import":
            text = body.get("csv")
            if not isinstance(text, str) or not text.strip():
                return self._err("csv is required")
            try:
                return self._json(h.import_csv(text))
            except ValueError as e:
                return self._err(str(e))

        return self._err("not found", 404)


def serve(tracker: Tracker, host: str = "127.0.0.1", port: int = 8817,
          history: History | None = None):
    Handler.tracker = tracker
    Handler.history = history or History()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd
