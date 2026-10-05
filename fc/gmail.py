"""Reading flight confirmations out of a person's Gmail.

Scope is `gmail.readonly`, requested separately from sign-in so nobody is asked
for their inbox just to log in — they opt in when they want the feature, and
revoking it leaves their account working.

Two deliberate limits, because this reads someone's mail:

* **We only ever fetch messages the search matched.** The query is narrow and
  anchored on travel words; we do not page the whole mailbox.
* **Nothing is stored but the extracted flight.** Message bodies are parsed in
  memory and dropped. The only durable artefacts are the user's refresh token
  and the flights they chose to import.

The refresh token is a key to someone's mail, so it lives in the database inside
the owner-only data directory, the same place the session-signing key lives. On
a shared host, put `WINGMATES_DATA_DIR` on a volume only this service can read.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

# Anchored on the words airlines actually use in confirmations. Broad enough to
# catch carriers we have never heard of, narrow enough that we are not reading
# someone's correspondence. Promotional mail that slips through is filtered
# again by `itinerary.looks_promotional`.
DEFAULT_QUERY = (
    '{subject:(itinerary OR "booking confirmation" OR "flight confirmation" '
    'OR "e-ticket" OR eticket OR "boarding pass" OR "your trip" '
    'OR "travel confirmation" OR "check-in")} '
    '-category:promotions -in:spam -in:trash'
)

MAX_MESSAGES = 150          # one scan's ceiling; keeps us inside free quota
REQUEST_TIMEOUT = 20


class GmailError(RuntimeError):
    """Something went wrong talking to Google. The message is shown to the user,
    so it says what to do rather than what broke internally."""


@dataclass
class Message:
    id: str
    subject: str
    html: str
    text: str
    received: datetime | None


# --------------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------------

def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    """`access_type=offline` plus `prompt=consent` is what makes Google hand
    back a refresh token. Without both, a re-connect silently yields no refresh
    token and the link dies at the first expiry."""
    from urllib.parse import urlencode
    return AUTH_ENDPOINT + "?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    })


def exchange_code(client_id: str, client_secret: str, code: str,
                  redirect_uri: str) -> dict:
    response = requests.post(TOKEN_ENDPOINT, timeout=REQUEST_TIMEOUT, data={
        "client_id": client_id, "client_secret": client_secret,
        "code": code, "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    })
    if response.status_code != 200:
        raise GmailError("Google refused the connection. Try connecting again.")
    payload = response.json()
    if not payload.get("refresh_token"):
        raise GmailError(
            "Google did not return a lasting permission. Remove Wingmates at "
            "myaccount.google.com/permissions, then connect again.")
    return payload


def refresh_access_token(client_id: str, client_secret: str,
                         refresh_token: str) -> str:
    response = requests.post(TOKEN_ENDPOINT, timeout=REQUEST_TIMEOUT, data={
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    })
    if response.status_code != 200:
        raise GmailError(
            "Gmail access has expired or been withdrawn. Connect Gmail again.")
    token = response.json().get("access_token")
    if not token:
        raise GmailError("Google returned no access token. Connect again.")
    return token


def revoke(token: str) -> None:
    """Best effort. A failure here must not stop us forgetting the token
    locally — the user asked to disconnect, so disconnect."""
    try:
        requests.post(REVOKE_ENDPOINT, data={"token": token},
                      timeout=REQUEST_TIMEOUT)
    except requests.RequestException:
        pass


# --------------------------------------------------------------------------
# Reading mail
# --------------------------------------------------------------------------

def _decode(data: str) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", "replace")
    except (ValueError, TypeError):
        return ""


def _collect_parts(part: dict, out: dict) -> None:
    """Walk the MIME tree, keeping the first HTML and the first plain part.

    Real confirmations nest: multipart/mixed wrapping multipart/alternative
    wrapping the parts we want, often with a PDF ticket alongside.
    """
    mime = (part.get("mimeType") or "").lower()
    data = (part.get("body") or {}).get("data") or ""
    if data:
        if mime == "text/html" and not out.get("html"):
            out["html"] = _decode(data)
        elif mime == "text/plain" and not out.get("text"):
            out["text"] = _decode(data)
    for child in part.get("parts") or ():
        _collect_parts(child, out)


class GmailClient:
    def __init__(self, access_token: str, session=None):
        self._token = access_token
        self._session = session or requests

    def _get(self, path: str, **params) -> dict:
        try:
            response = self._session.get(
                f"{API_ROOT}{path}",
                headers={"Authorization": f"Bearer {self._token}"},
                params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as error:
            raise GmailError(f"Could not reach Gmail: {error}") from error
        if response.status_code == 401:
            raise GmailError("Gmail access expired. Connect Gmail again.")
        if response.status_code == 403:
            raise GmailError(
                "Google declined the request. Check that the Gmail API is "
                "enabled for this project and that you granted read access.")
        if response.status_code == 429:
            raise GmailError("Google is rate-limiting us. Try again in a minute.")
        if response.status_code != 200:
            raise GmailError(f"Gmail returned {response.status_code}.")
        return response.json()

    def search(self, query: str = DEFAULT_QUERY,
               limit: int = MAX_MESSAGES) -> list[str]:
        ids: list[str] = []
        page_token = None
        while len(ids) < limit:
            params = {"q": query, "maxResults": min(100, limit - len(ids))}
            if page_token:
                params["pageToken"] = page_token
            payload = self._get("/messages", **params)
            ids += [m["id"] for m in payload.get("messages") or ()]
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return ids[:limit]

    def message(self, message_id: str) -> Message:
        payload = self._get(f"/messages/{message_id}", format="full")
        headers = {
            (h.get("name") or "").lower(): h.get("value") or ""
            for h in (payload.get("payload") or {}).get("headers") or ()
        }
        parts: dict[str, str] = {}
        _collect_parts(payload.get("payload") or {}, parts)

        received = None
        if raw := payload.get("internalDate"):
            try:
                received = datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
            except (ValueError, TypeError):
                received = None

        return Message(
            id=message_id,
            subject=headers.get("subject", ""),
            html=parts.get("html", ""),
            text=parts.get("text", ""),
            received=received,
        )


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

class GmailLinks:
    """One row per connected account. Deleting a user cascades, so an account
    deletion also forgets the token."""

    def __init__(self, database):
        self._db = database

    def _connect(self):
        from . import db as db_mod
        return db_mod.connect(self._db)

    def save(self, user_id: int, refresh_token: str, email: str = "") -> None:
        from contextlib import closing
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with closing(self._connect()) as db:
            db.execute(
                "INSERT INTO gmail_links (user_id, refresh_token, email,"
                " connected_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(user_id) DO UPDATE SET refresh_token = excluded"
                ".refresh_token, email = excluded.email,"
                " connected_at = excluded.connected_at",
                (user_id, refresh_token, email or "", now))
            db.commit()

    def get(self, user_id: int) -> dict | None:
        from contextlib import closing
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT user_id, email, connected_at, last_scan_at,"
                " refresh_token FROM gmail_links WHERE user_id = ?",
                (user_id,)).fetchone()
        return dict(row) if row else None

    def status(self, user_id: int) -> dict:
        """What the UI may see. Deliberately omits the token."""
        link = self.get(user_id)
        if not link:
            return {"connected": False}
        return {"connected": True, "email": link["email"],
                "connected_at": link["connected_at"],
                "last_scan_at": link["last_scan_at"]}

    def touch_scan(self, user_id: int) -> None:
        from contextlib import closing
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with closing(self._connect()) as db:
            db.execute("UPDATE gmail_links SET last_scan_at = ?"
                       " WHERE user_id = ?", (now, user_id))
            db.commit()

    def forget(self, user_id: int) -> str:
        """Remove the link and hand back the token so the caller can revoke it
        at Google too. Disconnecting here but leaving the grant standing would
        be a lie about what we can still read."""
        from contextlib import closing
        link = self.get(user_id)
        with closing(self._connect()) as db:
            db.execute("DELETE FROM gmail_links WHERE user_id = ?", (user_id,))
            db.commit()
        return (link or {}).get("refresh_token", "")


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------

def scan(client: GmailClient, already_flown=(), query: str = DEFAULT_QUERY,
         limit: int = MAX_MESSAGES) -> dict:
    """Search, extract, de-duplicate. Returns proposals, never writes anything.

    Nothing is imported here on purpose. A wrong flight silently added to
    someone's log is worse than one they had to tick, so the human is always
    the last step.
    """
    from . import itinerary

    message_ids = client.search(query=query, limit=limit)
    candidates: list[itinerary.Candidate] = []
    unreadable = 0

    for message_id in message_ids:
        try:
            message = client.message(message_id)
        except GmailError:
            unreadable += 1
            continue
        candidates += itinerary.extract(
            subject=message.subject, html=message.html, text=message.text,
            source_id=message.id)

    proposals = itinerary.dedupe(candidates, already_flown)
    return {
        "scanned": len(message_ids),
        "unreadable": unreadable,
        "found": len(candidates),
        "proposals": [c.to_json() for c in proposals],
        "high_confidence": sum(1 for c in proposals
                               if c.confidence == itinerary.HIGH),
    }
