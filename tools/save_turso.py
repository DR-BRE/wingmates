#!/usr/bin/env python3
"""Save your Turso database address and token to ~/.wingmates/turso.json.

The token is typed at a hidden prompt, so it is not shown on screen, kept in
your shell history, or pasted anywhere else.

    .venv/bin/python tools/save_turso.py
"""
import getpass
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.turso import Turso


def main() -> int:
    url = input("Turso database URL (starts with libsql://): ").strip()
    token = getpass.getpass("Turso auth token (hidden): ").strip()
    try:
        Turso(url, token)
    except ValueError as e:
        print(f"Not saved: {e}")
        return 1
    folder = Path.home() / ".wingmates"
    folder.mkdir(mode=0o700, exist_ok=True)
    path = folder / "turso.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"url": url, "token": token}, f)
    os.chmod(path, 0o600)
    print(f"Saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
