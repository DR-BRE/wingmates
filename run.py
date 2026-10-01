#!/usr/bin/env python3
"""Wingmates — your flight history on a globe, plus a live flight tracker.

    python3 run.py                 # start on http://127.0.0.1:8817
    python3 run.py --port 9000
    python3 run.py --no-browser
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import webbrowser

from fc import tracker as tracker_mod
from fc.config import Config
from fc.tracker import POLL_INTERVAL_S, Tracker
from fc.webapp import create_app

BANNER = r"""
  █   █  ███  █   █   ███   █   █   ███   █████  █████   ████
  █   █   █   ██  █  █      ██ ██  █   █    █    █      █    
  █ █ █   █   █ █ █  █  ██  █ █ █  █████    █    ████    ███ 
  ██ ██   █   █  ██  █   █  █   █  █   █    █    █          █
  █   █  ███  █   █   ███   █   █  █   █    █    █████  ████ 

  your flights on a globe · live ADS-B tracking
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8817)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    try:
        cfg = Config.from_env()
    except ValueError as e:
        print(f"  configuration error: {e}")
        return 1

    print(BANNER)
    tracker = None
    if cfg.live:
        # The tracker reads these module globals when it loads and saves.
        tracker_mod.STATE_DIR = cfg.data_dir
        tracker_mod.STATE_FILE = cfg.data_dir / "state.json"
        tracker = Tracker()
        if tracker.flights:
            print(f"  resumed {len(tracker.flights)} tracked flight(s)")

    app = create_app(cfg, tracker)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    url = f"http://{args.host}:{args.port}"
    print(f"  open   {url}")
    print(f"  data   {cfg.data_dir}")
    if tracker:
        print(f"  live   adsb.lol (primary) · opensky (fallback),"
              f" every {POLL_INTERVAL_S}s")
    else:
        print("  live   off")
    if cfg.dev_users:
        print("  dev    user switching is ON; do not expose this server")
    print("\n  ctrl-c to stop.\n")

    if tracker:
        tracker.start()
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)
    finally:
        if tracker:
            tracker.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
