"""Gmail connection, scanning and import. Offline — no network, fake clients."""
import base64
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc import db, gmail
from fc.gmail import GmailClient, GmailError, GmailLinks, Message
from tests.helpers import stores
from tests.test_webapp import WebCase


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


RESERVATION_HTML = (
    '<script type="application/ld+json">'
    '{"@type": "FlightReservation", "reservationFor": {"@type": "Flight",'
    ' "flightNumber": "110",'
    ' "airline": {"@type": "Airline", "iataCode": "AA"},'
    ' "departureAirport": {"@type": "Airport", "iataCode": "ATL"},'
    ' "departureTime": "2027-03-04T20:15:00-05:00",'
    ' "arrivalAirport": {"@type": "Airport", "iataCode": "JFK"}}}'
    '</script>')


class FakeGmailClient:
    """Stands in for the Gmail API. Records what it was asked for, so tests can
    assert we are not reading more mail than the search matched."""

    def __init__(self, messages, failing=()):
        self.messages = messages
        self.failing = set(failing)
        self.fetched: list[str] = []
        self.queries: list[str] = []

    def search(self, query=gmail.DEFAULT_QUERY, limit=gmail.MAX_MESSAGES):
        self.queries.append(query)
        return list(self.messages)[:limit]

    def message(self, message_id):
        self.fetched.append(message_id)
        if message_id in self.failing:
            raise GmailError("could not read that message")
        return self.messages[message_id]


def confirmation(message_id="m1", subject="Your trip confirmation"):
    return Message(id=message_id, subject=subject, html=RESERVATION_HTML,
                   text="", received=None)


# ---------------------------------------------------------------- OAuth URL

class TestAuthorizeUrl(unittest.TestCase):

    def test_asks_for_a_lasting_permission(self):
        """Without both access_type=offline and prompt=consent, Google returns
        no refresh token and the link dies at the first expiry."""
        url = gmail.authorize_url("cid", "https://x.test/cb", "state123")
        self.assertIn("access_type=offline", url)
        self.assertIn("prompt=consent", url)
        self.assertIn("state=state123", url)

    def test_asks_only_for_read_access(self):
        url = gmail.authorize_url("cid", "https://x.test/cb", "s")
        self.assertIn("gmail.readonly", url)
        self.assertNotIn("gmail.modify", url)
        self.assertNotIn("mail.google.com", url)


# ------------------------------------------------------------- MIME walking

class TestMessageParsing(unittest.TestCase):

    def test_finds_parts_nested_inside_multipart_wrappers(self):
        tree = {"mimeType": "multipart/mixed", "parts": [
            {"mimeType": "multipart/alternative", "parts": [
                {"mimeType": "text/plain", "body": {"data": b64("plain")}},
                {"mimeType": "text/html", "body": {"data": b64("<p>rich</p>")}}]},
            {"mimeType": "application/pdf", "body": {"data": b64("ticket")}}]}
        out = {}
        gmail._collect_parts(tree, out)
        self.assertEqual(out, {"text": "plain", "html": "<p>rich</p>"})

    def test_undecodable_data_yields_empty_rather_than_raising(self):
        self.assertEqual(gmail._decode("!!!not base64!!!"), "")

    def test_missing_body_is_tolerated(self):
        out = {}
        gmail._collect_parts({"mimeType": "text/html"}, out)
        self.assertEqual(out, {})


# ------------------------------------------------------------------- Errors

class TestApiErrors(unittest.TestCase):

    def client_returning(self, status):
        session = mock.Mock()
        session.get.return_value = mock.Mock(status_code=status,
                                             json=lambda: {})
        return GmailClient("token", session=session)

    def test_expired_access_says_to_reconnect(self):
        with self.assertRaises(GmailError) as caught:
            self.client_returning(401).search()
        self.assertIn("Connect Gmail again", str(caught.exception))

    def test_rate_limiting_says_to_wait(self):
        with self.assertRaises(GmailError) as caught:
            self.client_returning(429).search()
        self.assertIn("rate-limiting", str(caught.exception))

    def test_forbidden_points_at_the_likely_cause(self):
        with self.assertRaises(GmailError) as caught:
            self.client_returning(403).search()
        self.assertIn("Gmail API is enabled", str(caught.exception))


# ------------------------------------------------------------------ Scanning

class TestScan(unittest.TestCase):

    def test_proposes_a_flight_from_a_confirmation(self):
        client = FakeGmailClient({"m1": confirmation()})
        result = gmail.scan(client)
        self.assertEqual(result["scanned"], 1)
        self.assertEqual(len(result["proposals"]), 1)
        self.assertEqual(result["high_confidence"], 1)
        proposal = result["proposals"][0]
        self.assertEqual((proposal["date"], proposal["from"], proposal["to"]),
                         ("2027-03-04", "ATL", "JFK"))

    def test_collapses_repeat_emails_about_one_leg(self):
        """Confirmation, check-in and boarding pass all describe the same
        flight. Without de-duplication one trip arrives three times."""
        client = FakeGmailClient({
            "m1": confirmation("m1", "Your trip confirmation"),
            "m2": confirmation("m2", "Check-in is open"),
            "m3": confirmation("m3", "Your boarding pass")})
        result = gmail.scan(client)
        self.assertEqual(result["found"], 3)
        self.assertEqual(len(result["proposals"]), 1)

    def test_omits_flights_already_logged(self):
        client = FakeGmailClient({"m1": confirmation()})
        result = gmail.scan(client,
                            already_flown=[("2027-03-04", "ATL", "JFK")])
        self.assertEqual(result["proposals"], [])

    def test_one_unreadable_message_does_not_abort_the_scan(self):
        client = FakeGmailClient({"m1": confirmation(), "m2": confirmation("m2")},
                                 failing=["m1"])
        result = gmail.scan(client)
        self.assertEqual(result["unreadable"], 1)
        self.assertEqual(len(result["proposals"]), 1)

    def test_reads_only_what_the_search_matched(self):
        client = FakeGmailClient({"m1": confirmation()})
        gmail.scan(client)
        self.assertEqual(client.fetched, ["m1"])

    def test_the_search_excludes_promotions_spam_and_trash(self):
        client = FakeGmailClient({})
        gmail.scan(client)
        query = client.queries[0]
        for excluded in ("-category:promotions", "-in:spam", "-in:trash"):
            self.assertIn(excluded, query)

    def test_scanning_writes_nothing(self):
        """A scan proposes; a human disposes. Nothing may import itself."""
        client = FakeGmailClient({"m1": confirmation()})
        result = gmail.scan(client)
        self.assertIn("proposals", result)
        self.assertNotIn("added", result)


# ------------------------------------------------------------------ Storage

class TestGmailLinks(unittest.TestCase):

    def setUp(self):
        self.dir, self.airports, self.history, self.users = stores(self)
        db.init(self.database)
        self.links = GmailLinks(self.database)
        self.user = self.users.create("Brett", "brett")

    def test_an_unconnected_account_reports_not_connected(self):
        self.assertEqual(self.links.status(self.user["id"]),
                         {"connected": False})

    def test_saving_then_reading_back(self):
        self.links.save(self.user["id"], "refresh-abc", "brett@example.test")
        status = self.links.status(self.user["id"])
        self.assertTrue(status["connected"])
        self.assertEqual(status["email"], "brett@example.test")

    def test_status_never_exposes_the_token(self):
        self.links.save(self.user["id"], "refresh-abc", "brett@example.test")
        self.assertNotIn("refresh_token", self.links.status(self.user["id"]))

    def test_reconnecting_replaces_the_token(self):
        self.links.save(self.user["id"], "old", "a@b.test")
        self.links.save(self.user["id"], "new", "a@b.test")
        self.assertEqual(self.links.get(self.user["id"])["refresh_token"], "new")

    def test_forget_returns_the_token_so_it_can_be_revoked(self):
        self.links.save(self.user["id"], "refresh-abc")
        self.assertEqual(self.links.forget(self.user["id"]), "refresh-abc")
        self.assertEqual(self.links.status(self.user["id"]),
                         {"connected": False})

    def test_forgetting_an_unconnected_account_is_harmless(self):
        self.assertEqual(self.links.forget(self.user["id"]), "")

    def test_deleting_the_account_forgets_the_token(self):
        self.links.save(self.user["id"], "refresh-abc")
        self.users.delete(self.user["id"])
        self.assertIsNone(self.links.get(self.user["id"]))


# -------------------------------------------------------------------- Routes

class TestGmailRoutes(WebCase):

    def test_status_reports_unavailable_without_google_signin(self):
        client = self.login("brett")
        payload = client.get("/api/gmail/status").get_json()
        self.assertFalse(payload["connected"])
        self.assertFalse(payload["available"])

    def test_scanning_without_google_signin_is_refused(self):
        client = self.login("brett")
        response = self.post("/api/gmail/scan", {}, client)
        self.assertEqual(response.status_code, 409)

    def test_import_requires_at_least_one_flight(self):
        client = self.login("brett")
        self.assertEqual(self.post("/api/gmail/import", {}, client).status_code,
                         400)
        self.assertEqual(
            self.post("/api/gmail/import", {"flights": []}, client).status_code,
            400)

    def test_import_adds_chosen_flights(self):
        client = self.login("brett")
        response = self.post("/api/gmail/import", {"flights": [
            {"date": "2027-03-04", "from": "ATL", "to": "JFK",
             "airline": "American", "flight_number": "AA110"}]}, client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["added"], 1)
        logged = client.get("/api/history").get_json()["flights"]
        self.assertEqual(logged[0]["flight_number"], "AA110")

    def test_import_skips_a_flight_already_logged(self):
        client = self.login("brett")
        flight = {"date": "2027-03-04", "from": "ATL", "to": "JFK"}
        self.post("/api/gmail/import", {"flights": [flight]}, client)
        again = self.post("/api/gmail/import", {"flights": [flight]}, client)
        payload = again.get_json()
        self.assertEqual((payload["added"], payload["skipped"]), (0, 1))

    def test_import_skips_duplicates_inside_one_request(self):
        client = self.login("brett")
        flight = {"date": "2027-03-04", "from": "ATL", "to": "JFK"}
        payload = self.post("/api/gmail/import",
                            {"flights": [flight, flight]}, client).get_json()
        self.assertEqual((payload["added"], payload["skipped"]), (1, 1))

    def test_a_bad_airport_is_reported_not_raised(self):
        client = self.login("brett")
        payload = self.post("/api/gmail/import", {"flights": [
            {"date": "2027-03-04", "from": "ZZZ", "to": "JFK"}]},
            client).get_json()
        self.assertEqual(payload["added"], 0)
        self.assertTrue(payload["errors"])

    def test_one_bad_flight_does_not_stop_the_good_ones(self):
        client = self.login("brett")
        payload = self.post("/api/gmail/import", {"flights": [
            {"date": "2027-03-04", "from": "ZZZ", "to": "JFK"},
            {"date": "2027-03-05", "from": "ATL", "to": "JFK"}]},
            client).get_json()
        self.assertEqual(payload["added"], 1)
        self.assertEqual(len(payload["errors"]), 1)

    def test_import_is_capped(self):
        client = self.login("brett")
        many = [{"date": "2027-03-04", "from": "ATL", "to": "JFK"}] * 501
        self.assertEqual(
            self.post("/api/gmail/import", {"flights": many}, client).status_code,
            400)

    def test_disconnect_is_safe_when_never_connected(self):
        client = self.login("brett")
        response = self.post("/api/gmail/disconnect", {}, client)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["connected"])

    def test_another_account_cannot_see_your_connection(self):
        brett = self.login("brett")
        other = self.login("sam")
        GmailLinks(self.database).save(
            brett.get("/api/me").get_json()["id"], "tok", "b@x.test")
        self.assertFalse(other.get("/api/gmail/status").get_json()["connected"])


if __name__ == "__main__":
    unittest.main()
