"""Sign-in tests, through Flask's test client, with a fake in place of Google.
Offline."""
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import redirect

from fc.config import Config
from fc.hosted import build
from fc.webapp import create_app
from tests.helpers import stores

BASE = "http://localhost"
ORIGIN = {"Origin": BASE}
BRETT = {"sub": "g-1", "email": "brett@example.com", "name": "Brett F",
         "picture_url": "https://img.example/b.png"}
ANN = {"sub": "g-2", "email": "ann@example.com", "name": "Ann", "picture_url": None}


class FakeSignIn:
    """Stands in for Google: begin() goes straight to the callback, and
    finish() returns whatever profile the test set."""
    def __init__(self):
        self.profile = None
        self.redirect_uri = None

    def begin(self, redirect_uri):
        self.redirect_uri = redirect_uri
        return redirect("/auth/callback")

    def finish(self):
        return self.profile


class SignInCase(unittest.TestCase):
    def setUp(self):
        self.dir, self.airports, self.history, self.users = stores(self)
        self.google = FakeSignIn()
        self.app = create_app(
            Config(auth="google", live=False, data_dir=self.dir, base_url=BASE,
                   google_client_id="id", google_client_secret="secret"),
            airports=self.airports, sign_in=self.google)
        self.client = self.app.test_client()

    def post(self, path, body=None, client=None):
        return (client or self.client).post(path, json=body or {}, headers=ORIGIN)

    def sign_in(self, profile=BRETT, username=None, next=None):
        """A new browser, signed in as `profile`. Returns (client, the
        response to the callback)."""
        client = self.app.test_client()
        self.google.profile = profile
        start = client.get("/auth/login" + (f"?next={quote(next)}" if next else ""))
        done = client.get(start.headers["Location"])
        if username:
            self.assertEqual(self.post("/api/username", {"username": username},
                                       client).status_code, 200)
        return client, done


class TestSignedOut(SignInCase):

    def test_every_api_route_answers_401(self):
        checked = 0
        for rule in self.app.url_map.iter_rules():
            if not rule.rule.startswith("/api/"):
                continue
            path = re.sub(r"<[^>]+>", "1", rule.rule)
            for method in rule.methods & {"GET", "POST"}:
                r = (self.client.get(path) if method == "GET"
                     else self.post(path))
                self.assertEqual((r.status_code, r.get_json()),
                                 (401, {"error": "sign in required"}),
                                 f"{method} {path}")
                checked += 1
        self.assertGreaterEqual(checked, 18)

    def test_pages_send_you_to_the_sign_in_page(self):
        self.assertEqual(self.client.get("/").headers["Location"], "/login")
        self.assertEqual(self.client.get("/welcome").headers["Location"], "/login")
        with self.client.get("/login") as r:
            self.assertEqual(r.status_code, 200)
            self.assertIn(b"Continue with Google", r.data)

    def test_static_files_need_no_sign_in(self):
        with self.client.get("/static/style.css") as r:
            self.assertEqual(r.status_code, 200)


    def test_the_health_check_needs_no_sign_in(self):
        r = self.client.get("/healthz", base_url="http://10.214.3.7:10000")
        self.assertEqual((r.status_code, r.get_json()), (200, {"ok": True}))

class TestSignIn(SignInCase):

    def test_google_is_asked_to_return_to_the_configured_address(self):
        self.sign_in()
        self.assertEqual(self.google.redirect_uri, BASE + "/auth/callback")

    def test_a_new_account_must_choose_a_username_before_anything_else(self):
        client, done = self.sign_in()
        self.assertEqual(done.headers["Location"], "/")
        self.assertEqual(client.get("/").headers["Location"], "/welcome")
        me = client.get("/api/me").get_json()
        self.assertEqual((me["username"], me["name"], me["auth"]),
                         (None, "Brett F", "google"))
        self.assertNotIn("email", me)
        for path in ("/api/history", "/api/social", "/api/airports?q=atl"):
            r = client.get(path)
            self.assertEqual((r.status_code, r.get_json()),
                             (409, {"error": "choose a username first"}), path)
        with client.get("/welcome") as r:
            self.assertEqual(r.status_code, 200)

    def test_choosing_a_username_opens_the_app(self):
        client, _ = self.sign_in()
        r = self.post("/api/username", {"username": "@Brett"}, client)
        self.assertEqual((r.status_code, r.get_json()["username"]), (200, "brett"))
        with client.get("/") as page:
            self.assertEqual(page.status_code, 200)
        self.assertEqual(client.get("/api/history").status_code, 200)
        self.assertEqual(client.get("/welcome").headers["Location"], "/")
        self.assertEqual(client.get("/login").headers["Location"], "/")

    def test_username_problems_are_explained(self):
        self.sign_in(ANN, username="ann")
        client, _ = self.sign_in()
        for bad, word in (("ab", "3 to 20"), ("admin", "reserved"),
                          ("Ann", "taken"), (None, "3 to 20"), (["x"], "3 to 20")):
            r = self.post("/api/username", {"username": bad}, client)
            self.assertEqual(r.status_code, 400, repr(bad))
            self.assertIn(word, r.get_json()["error"])
        self.post("/api/username", {"username": "brett"}, client)
        r = self.post("/api/username", {"username": "other"}, client)
        self.assertEqual(r.status_code, 400)
        self.assertIn("already", r.get_json()["error"])

    def test_signing_in_again_reuses_the_account(self):
        first, _ = self.sign_in(username="brett")
        uid = first.get("/api/me").get_json()["id"]
        again, _ = self.sign_in({**BRETT, "email": "moved@example.com",
                                 "name": "Brett Francoeur"})
        me = again.get("/api/me").get_json()
        self.assertEqual((me["id"], me["username"], me["name"]),
                         (uid, "brett", "Brett Francoeur"))

    def test_a_cancelled_sign_in_returns_to_the_sign_in_page(self):
        client, done = self.sign_in(profile=None)
        self.assertEqual(done.headers["Location"], "/login?error=1")
        self.assertEqual(client.get("/api/me").status_code, 401)

    def test_the_return_address_is_used_only_if_it_is_on_this_site(self):
        _, done = self.sign_in(next="/?tab=social")
        self.assertEqual(done.headers["Location"], "/?tab=social")
        for bad in ("https://evil.example", "//evil.example", "/\\evil.example"):
            _, done = self.sign_in(next=bad)
            self.assertEqual(done.headers["Location"], "/", bad)


class TestSessions(SignInCase):

    def test_the_cookie_is_httponly_lax_and_lasts_thirty_days(self):
        self.google.profile = BRETT
        client = self.app.test_client()
        done = client.get(client.get("/auth/login").headers["Location"])
        cookie = done.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Expires=", cookie)
        self.assertNotIn("Secure", cookie)        # the base URL here is http

    def test_sign_out_ends_the_session(self):
        client, _ = self.sign_in(username="brett")
        self.assertEqual(self.post("/auth/logout", client=client).get_json(),
                         {"ok": True})
        self.assertEqual(client.get("/api/me").status_code, 401)
        self.assertEqual(client.get("/auth/logout").status_code, 405)

    def test_a_session_for_a_deleted_account_is_signed_out(self):
        client, _ = self.sign_in(username="brett")
        uid = client.get("/api/me").get_json()["id"]
        self.users.delete(uid)
        ann, _ = self.sign_in(ANN, username="ann")
        r = client.get("/api/me")
        self.assertEqual((r.status_code, r.get_json()),
                         (401, {"error": "sign in required"}))
        self.assertEqual(ann.get("/api/me").get_json()["username"], "ann")

    def test_page_requests_on_another_local_name_move_to_the_configured_one(self):
        r = self.client.get("/?tab=social", base_url="http://127.0.0.1")
        self.assertEqual((r.status_code, r.headers["Location"]),
                         (302, BASE + "/?tab=social"))
        r = self.client.get("/auth/login", base_url="http://127.0.0.1")
        self.assertEqual(r.headers["Location"], BASE + "/auth/login")
        # API calls are answered, not redirected.
        self.assertEqual(self.client.get("/api/me",
                                         base_url="http://127.0.0.1").status_code, 401)


    def test_signing_out_ends_every_session_of_the_account(self):
        phone, _ = self.sign_in(username="brett")
        laptop, _ = self.sign_in()
        copied = self.app.test_client()
        copied.set_cookie("session", phone.get_cookie("session").value)
        ann, _ = self.sign_in(ANN, username="ann")
        for client in (phone, laptop, copied):
            self.assertEqual(client.get("/api/me").status_code, 200)

        self.post("/auth/logout", client=phone)
        for client in (phone, laptop, copied):
            self.assertEqual(client.get("/api/me").status_code, 401)
        self.assertEqual(ann.get("/api/me").get_json()["username"], "ann")

        again, _ = self.sign_in()
        self.assertEqual(again.get("/api/me").get_json()["username"], "brett")
        self.assertEqual(copied.get("/api/me").status_code, 401)

    def test_a_cookie_from_before_session_epochs_is_asked_to_sign_in(self):
        client, _ = self.sign_in(username="brett")
        uid = client.get("/api/me").get_json()["id"]
        old = self.app.test_client()
        with old.session_transaction() as s:
            s["uid"] = uid                      # no epoch, as issued before
        r = old.get("/api/me")
        self.assertEqual((r.status_code, r.get_json()),
                         (401, {"error": "sign in required"}))
        self.assertEqual(old.get("/").headers["Location"], "/login")

    def test_signing_out_while_signed_out_is_harmless(self):
        self.assertEqual(self.post("/auth/logout").get_json(), {"ok": True})

class TestAccountDelete(SignInCase):

    def test_it_needs_the_word_delete(self):
        client, _ = self.sign_in(username="brett")
        for confirm in (None, "delete", "yes", True):
            r = self.post("/api/account/delete", {"confirm": confirm}, client)
            self.assertEqual(r.status_code, 400, repr(confirm))
        self.assertEqual(client.get("/api/me").status_code, 200)

    def test_it_removes_the_account_its_flights_and_frees_the_username(self):
        client, _ = self.sign_in(username="brett")
        uid = client.get("/api/me").get_json()["id"]
        self.post("/api/history", {"date": "2024-03-09", "from": "ATL",
                                   "to": "LHR"}, client)
        self.assertEqual(self.post("/api/account/delete", {"confirm": "DELETE"},
                                   client).get_json(), {"ok": True})
        self.assertEqual(client.get("/api/me").status_code, 401)
        self.assertIsNone(self.users.get(uid))
        self.assertEqual(self.history.for_user(uid).list(), [])
        again, _ = self.sign_in(username="brett")
        self.assertNotEqual(again.get("/api/me").get_json()["id"], uid)

    def test_an_account_with_no_username_can_still_be_deleted(self):
        client, _ = self.sign_in()
        self.assertEqual(self.post("/api/account/delete", {"confirm": "DELETE"},
                                   client).status_code, 200)


class TestTwoPeople(SignInCase):

    def test_two_signed_in_people_can_become_mates(self):
        brett, _ = self.sign_in(username="brett")
        ann, _ = self.sign_in(ANN, username="ann")
        self.post("/api/history", {"date": "2024-03-09", "from": "ATL",
                                   "to": "LHR"}, ann)
        self.post("/api/mates/request", {"username": "ann"}, brett)
        brett_id = brett.get("/api/me").get_json()["id"]
        self.post(f"/api/mates/{brett_id}/accept", client=ann)
        mate = brett.get("/api/social").get_json()["mates"][0]
        self.assertEqual((mate["username"], mate["name"]), ("ann", "Ann"))
        self.assertNotIn("email", mate)


class TestLocalModeIsUnchanged(unittest.TestCase):

    def setUp(self):
        self.dir, self.airports, _, _ = stores(self)
        self.client = create_app(Config(data_dir=self.dir, live=False),
                                 airports=self.airports).test_client()

    def test_sign_in_routes_do_not_exist(self):
        self.assertEqual(self.client.get("/auth/login").status_code, 404)
        self.assertEqual(self.client.get("/auth/callback").status_code, 404)
        for path in ("/auth/logout", "/api/username", "/api/account/delete"):
            r = self.client.post(path, json={}, headers=ORIGIN)
            self.assertEqual(r.status_code, 404, path)

    def test_gate_pages_lead_back_to_the_app(self):
        self.assertEqual(self.client.get("/login").headers["Location"], "/")
        self.assertEqual(self.client.get("/welcome").headers["Location"], "/")
        self.assertEqual(self.client.get("/api/me").get_json()["username"], "you")


class TestReviewFindings(SignInCase):

    def google_app(self, **over):
        settings = dict(auth="google", live=False, data_dir=self.dir, base_url=BASE,
                        google_client_id="id", google_client_secret="secret")
        return create_app(Config(**{**settings, **over}), airports=self.airports,
                          sign_in=self.google)

    def test_a_sign_in_that_cannot_start_returns_to_the_sign_in_page(self):
        def unreachable(redirect_uri):
            raise RuntimeError("could not reach Google")
        self.google.begin = unreachable
        with self.assertLogs(self.app.logger, "WARNING"):
            r = self.client.get("/auth/login")
        self.assertEqual((r.status_code, r.headers["Location"]),
                         (302, "/login?error=1"))

    def test_user_switching_never_exists_with_sign_in_on(self):
        app = self.google_app(dev_users=True)
        client = app.test_client()
        self.google.profile = BRETT
        client.get(client.get("/auth/login").headers["Location"])
        client.post("/api/username", json={"username": "brett"}, headers=ORIGIN)
        self.users.create("Victim", "victim")
        r = client.post("/dev/login", json={"username": "victim"}, headers=ORIGIN)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(client.get("/api/me").get_json()["username"], "brett")

    def test_the_spelling_of_the_base_url_cannot_cause_a_redirect_loop(self):
        for base in ("http://LocalHost", "http://localhost:80", "http://localhost/"):
            with self.google_app(base_url=base).test_client().get("/login") as r:
                self.assertEqual(r.status_code, 200, base)


class TestHosted(unittest.TestCase):

    def setUp(self):
        self.dir, self.airports, _, _ = stores(self)
        self.google = FakeSignIn()
        self.env = {"WINGMATES_AUTH": "google", "WINGMATES_DATA_DIR": str(self.dir),
                    "GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "secret",
                    "SECRET_KEY": "a-fixed-key", "WINGMATES_BASE_URL": BASE}

    def signed_in_cookie(self, app):
        client = app.test_client()
        self.google.profile = BRETT
        client.get(client.get("/auth/login").headers["Location"])
        return client.get_cookie("session").value

    def test_it_refuses_to_start_without_sign_in(self):
        for env in ({"WINGMATES_DATA_DIR": str(self.dir)},
                    {"WINGMATES_AUTH": "local", "WINGMATES_DATA_DIR": str(self.dir)}):
            with self.assertRaises(RuntimeError) as cm:
                build(env)
            self.assertIn("WINGMATES_AUTH=google", str(cm.exception))

    def test_it_builds_a_signed_out_app_that_passes_its_health_check(self):
        client = build(self.env, sign_in=self.google).test_client()
        self.assertEqual(client.get("/healthz").get_json(), {"ok": True})
        self.assertEqual(client.get("/").headers["Location"], "/login")
        self.assertEqual(client.get("/api/me").status_code, 401)

    def test_it_never_runs_the_live_tracker(self):
        app = build({**self.env, "WINGMATES_LIVE": "1"}, sign_in=self.google)
        client = app.test_client()
        client.set_cookie("session", self.signed_in_cookie(app))
        client.post("/api/username", json={"username": "brett"}, headers=ORIGIN)
        self.assertFalse(client.get("/api/me").get_json()["live"])
        self.assertEqual(client.get("/api/state").status_code, 404)

    def test_people_and_their_flights_survive_a_redeploy(self):
        first = build(self.env, sign_in=self.google)
        cookie = self.signed_in_cookie(first)
        before = first.test_client()
        before.set_cookie("session", cookie)
        before.post("/api/username", json={"username": "brett"}, headers=ORIGIN)
        before.post("/api/history", headers=ORIGIN,
                    json={"date": "2024-03-09", "from": "ATL", "to": "LHR"})

        # A redeploy is a new process over the same disk and the same settings.
        after = build(self.env, sign_in=self.google).test_client()
        after.set_cookie("session", cookie)
        self.assertEqual(after.get("/api/me").get_json()["username"], "brett")
        self.assertEqual(len(after.get("/api/history").get_json()["flights"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
