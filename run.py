#!/usr/bin/env python3
"""Wingmates — your flight history on a globe, plus a live flight tracker.

    python3 run.py                 # start on http://127.0.0.1:8817
    python3 run.py --port 9000
    python3 run.py --no-browser
"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from fc.server import serve
from fc.tracker import POLL_INTERVAL_S, Tracker

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

    print(BANNER)
    tracker = Tracker()
    if tracker.flights:
        print(f"  resumed {len(tracker.flights)} flight(s) from earlier today")

    try:
        httpd = serve(tracker, args.host, args.port)
    except OSError as e:
        print(f"  cannot bind {args.host}:{args.port} — {e}")
        print(f"  try: python3 run.py --port {args.port + 1}")
        return 1

    url = f"http://{args.host}:{args.port}"
    print(f"  open   {url}")
    print(f"  feed   adsb.lol (primary) · opensky (fallback)")
    print(f"  poll   every {POLL_INTERVAL_S}s per tracked flight")
    print(f"  state  ~/.flighty-clone/state.json · flights.db")
    print(f"\n  events appear below as they happen. ctrl-c to stop.\n")

    tracker.start()
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopping…")
    finally:
        tracker.stop()
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
