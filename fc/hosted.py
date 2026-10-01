"""The app as a hosted server runs it.

Kept apart from run.py because the two have different duties. run.py serves
one person on their own machine. This serves strangers, so it insists on
sign-in and never runs the live tracker, which polls free community feeds on
behalf of whoever is at the keyboard.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

from flask import Flask

from .config import Config
from .webapp import create_app


def build(env: Mapping[str, str] | None = None, sign_in=None) -> Flask:
    env = os.environ if env is None else env
    config = Config.from_env(env)
    if config.auth != "google":
        raise RuntimeError(
            "a hosted Wingmates needs WINGMATES_AUTH=google: without sign-in, "
            "every visitor would share one account")
    if config.turso is not None and not config.secret_key:
        raise RuntimeError(
            "with a Turso database, SECRET_KEY must be set: a host without a "
            "disk has nowhere to keep a generated session key")
    if env.get("VERCEL") and config.turso is None:
        raise RuntimeError(
            "on Vercel the data must live in Turso, because there is no disk: "
            "set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN")
    return create_app(config, tracker=None, sign_in=sign_in)
