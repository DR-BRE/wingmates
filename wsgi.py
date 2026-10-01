"""The entry point Vercel looks for: a Flask app named `app` in wsgi.py.

Builds the hosted app, which insists on sign-in. To run Wingmates on your own
machine use run.py instead.
"""
from fc.hosted import build

app = build()
