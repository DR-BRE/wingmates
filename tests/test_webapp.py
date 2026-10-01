"""Web layer tests, through Flask's test client. Offline."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.config import Config
from fc.webapp import create_app
from tests.helpers import stores

ORIGIN = {"Origin": "http://localhost"}


class FakeTracker:
    def snapshot(self):
        return {"flights": [], "alerts": [], "log": [], "status": {"tracked": 0}}


class WebCase(unittest.TestCase):
    dev_users = True
    tracker = None

    def setUp(self):
        self.dir, self.airports, self.history, self.users = stores(self)
        self.app = create_app(
            Config(data_dir=self.dir, dev_users=self.dev_users, live=False),
            tracker=self.tracker, airports=self.airports)
        self.client = self.app.test_client()

    def post(self, path, body=None, client=None, **kw):
        return (client or self.client).post(path, json=body or {},
                                            headers=ORIGIN, **kw)

    def login(self, username):
        client = self.app.test_client()
        self.assertEqual(self.post("/dev/login", {"username": username},
                                   client).status_code, 200)
        return client


class TestMe(WebCase):

    def test_requests_act_as_the_local_user(self):
        me = self.client.get("/api/me").get_json()
        self.assertEqual((me["username"], me["name"]), ("you", "You"))
        self.assertEqual((me["auth"], me["live"], me["dev_users"]),
                         ("local", False, True))
        self.assertNotIn("email", me)

    def test_dev_login_switches_user_and_back(self):
        ann = self.login("Ann")
        self.assertEqual(ann.get("/api/me").get_json()["username"], "ann")
        self.assertEqual(self.client.get("/api/me").get_json()["username"], "you")
        self.post("/dev/login", {"username": "you"}, ann)
        self.assertEqual(ann.get("/api/me").get_json()["username"], "you")

    def test_dev_login_refuses_a_bad_username(self):
        r = self.post("/dev/login", {"username": "no"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("3 to 20", r.get_json()["error"])

    def test_a_session_for_a_deleted_user_falls_back_to_the_local_user(self):
        ann = self.login("ann")
        self.users.delete(self.users.by_username("ann")["id"])
        r = ann.get("/api/me")
        self.assertEqual((r.status_code, r.get_json()["username"]), (200, "you"))


class TestGuard(WebCase):

    def test_a_post_without_a_matching_origin_is_refused(self):
        body = {"date": "2024-03-09", "from": "ATL", "to": "LHR"}
        for headers in ({}, {"Origin": "http://evil.example"},
                        {"Origin": "http://localhost:9999"}):
            r = self.client.post("/api/history", json=body, headers=headers)
            self.assertEqual(r.status_code, 403, headers)
        self.assertEqual(self.client.get("/api/history").get_json()["flights"], [])

    def test_a_post_that_is_not_json_is_refused(self):
        r = self.client.post("/api/history", data="date=2024-03-09",
                             headers=ORIGIN)
        self.assertEqual(r.status_code, 403)

    def test_a_body_that_is_not_a_json_object_is_a_400(self):
        for raw in ("[1, 2]", "{broken", '"text"'):
            r = self.client.post("/api/history", data=raw, headers=ORIGIN,
                                 content_type="application/json")
            self.assertEqual(r.status_code, 400, raw)
            self.assertIn("error", r.get_json())

    def test_unknown_api_paths_answer_in_json(self):
        r = self.client.get("/api/nope")
        self.assertEqual((r.status_code, r.get_json()), (404, {"error": "not found"}))


class TestHistoryRoutes(WebCase):

    def add(self, client=None, **over):
        body = {"date": "2024-03-09", "from": "ATL", "to": "LHR", **over}
        return self.post("/api/history", body, client)

    def test_add_list_update_delete(self):
        f = self.add(airline="Delta").get_json()
        self.assertEqual((f["from"]["iata"], f["airline"]), ("ATL", "Delta"))
        snap = self.client.get("/api/history").get_json()
        self.assertEqual(snap["stats"]["flights"], 1)
        g = self.post("/api/history/update",
                      {"id": f["id"], "date": "2024-03-10", "from": "ATL",
                       "to": "JFK"}).get_json()
        self.assertEqual((g["to"]["iata"], g["airline"]), ("JFK", ""))
        self.assertEqual(self.post("/api/history/delete",
                                   {"id": f["id"]}).get_json(), {"removed": True})

    def test_bad_input_is_a_400_with_the_reason(self):
        r = self.add(to="ZZZ")
        self.assertEqual(r.status_code, 400)
        self.assertIn("ZZZ", r.get_json()["error"])
        self.assertEqual(self.post("/api/history/update", {}).status_code, 400)
        self.assertEqual(self.post("/api/history/delete", {}).status_code, 400)
        self.assertEqual(self.post("/api/history/import", {}).status_code, 400)

    def test_users_cannot_touch_each_others_flights(self):
        ann, bob = self.login("ann"), self.login("bob")
        f = self.add(ann).get_json()
        self.assertEqual(bob.get("/api/history").get_json()["flights"], [])
        r = self.post("/api/history/update",
                      {"id": f["id"], "date": "2024-03-10", "from": "ATL",
                       "to": "JFK"}, bob)
        missing = self.post("/api/history/update",
                            {"id": 999, "date": "2024-03-10", "from": "ATL",
                             "to": "JFK"}, bob)
        self.assertEqual((r.status_code, r.get_json()),
                         (missing.status_code, missing.get_json()))
        self.assertEqual(self.post("/api/history/delete", {"id": f["id"]},
                                   bob).get_json(), {"removed": False})
        self.assertEqual(len(ann.get("/api/history").get_json()["flights"]), 1)

    def test_export_downloads_csv_that_imports_back(self):
        self.add(flight_number="DL30")
        r = self.client.get("/api/history/export.csv")
        self.assertTrue(r.headers["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment", r.headers["Content-Disposition"])
        bob = self.login("bob")
        self.assertEqual(self.post("/api/history/import",
                                   {"csv": r.get_data(as_text=True)},
                                   bob).get_json()["added"], 1)

    def test_template_and_airport_search(self):
        self.assertTrue(self.client.get("/api/history/template.csv")
                        .get_data(as_text=True).startswith("date,from,to"))
        found = self.client.get("/api/airports?q=lond").get_json()["airports"]
        self.assertEqual([a["iata"] for a in found], ["LHR"])


class TestModes(WebCase):
    dev_users = False

    def test_dev_login_does_not_exist_unless_enabled(self):
        self.assertEqual(self.post("/dev/login", {"username": "ann"}).status_code,
                         404)

    def test_live_routes_do_not_exist_without_a_tracker(self):
        self.assertEqual(self.client.get("/api/state").status_code, 404)
        self.assertEqual(self.post("/api/poll").status_code, 404)


class TestLive(WebCase):
    tracker = FakeTracker()

    def test_live_routes_exist_with_a_tracker(self):
        self.assertTrue(self.client.get("/api/me").get_json()["live"])
        self.assertEqual(self.client.get("/api/state").get_json()["status"],
                         {"tracked": 0})


class TestPages(WebCase):

    def test_index_and_static_files_are_served(self):
        with self.client.get("/") as r:
            self.assertIn(b"Wingmates", r.data)
        with self.client.get("/static/style.css") as r:
            self.assertEqual(r.status_code, 200)


PRIVATE = {"email", "date", "airline", "flight_number", "aircraft", "seat",
           "notes", "google_sub"}


def keys(obj):
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in keys(v)}
    return set()


class TestSocialRoutes(WebCase):

    def setUp(self):
        super().setUp()
        self.ann, self.bob = self.login("ann"), self.login("bob")
        self.bob_id = self.users.by_username("bob")["id"]
        self.ann_id = self.users.by_username("ann")["id"]
        self.post("/api/history", {"date": "2024-03-09", "from": "ATL",
                                   "to": "LHR", "airline": "Delta",
                                   "seat": "34A", "notes": "secret"}, self.bob)

    def test_lookup_takes_usernames_the_way_people_type_them(self):
        r = self.ann.get("/api/users/lookup?username=%40Bob%20")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {
            "id": self.bob_id, "username": "bob", "name": "bob",
            "picture_url": None, "relation": "none"})
        for q in ("bo", "nobody", ""):
            r = self.ann.get(f"/api/users/lookup?username={q}")
            self.assertEqual((r.status_code, r.get_json()),
                             (404, {"error": "no one has that username"}))

    def test_request_accept_compare_and_remove(self):
        r = self.post("/api/mates/request", {"username": "bob"}, self.ann)
        self.assertEqual(r.get_json()["relation"], "requested")
        s = self.bob.get("/api/social").get_json()
        self.assertEqual([p["username"] for p in s["incoming"]], ["ann"])

        self.assertEqual(self.post(f"/api/mates/{self.ann_id}/accept",
                                   client=self.bob).get_json(), {"ok": True})
        s = self.ann.get("/api/social").get_json()
        self.assertEqual(s["mates"][0]["username"], "bob")
        self.assertGreater(s["mates"][0]["stats"]["distance_mi"], 4000)
        self.assertEqual(keys(s) & PRIVATE, set())

        routes = self.ann.get(f"/api/mates/{self.bob_id}/routes").get_json()
        self.assertEqual([(r["from"]["iata"], r["to"]["iata"])
                          for r in routes["routes"]], [("ATL", "LHR")])
        self.assertEqual(keys(routes) & PRIVATE, set())

        self.assertEqual(self.post(f"/api/mates/{self.bob_id}/remove",
                                   client=self.ann).status_code, 200)
        self.assertEqual(self.bob.get("/api/social").get_json()["mates"], [])

    def test_decline_and_cancel(self):
        self.post("/api/mates/request", {"username": "bob"}, self.ann)
        self.assertEqual(self.post(f"/api/mates/{self.ann_id}/decline",
                                   client=self.bob).status_code, 200)
        self.assertEqual(self.post(f"/api/mates/{self.ann_id}/decline",
                                   client=self.bob).status_code, 404)
        self.assertEqual(self.post(f"/api/mates/{self.bob_id}/cancel",
                                   client=self.ann).status_code, 200)
        self.assertEqual(self.ann.get("/api/social").get_json()["outgoing"], [])

    def test_request_errors(self):
        r = self.post("/api/mates/request", {"username": "nobody"}, self.ann)
        self.assertEqual(r.status_code, 404)
        r = self.post("/api/mates/request", {"username": "ann"}, self.ann)
        self.assertEqual(r.status_code, 400)
        self.assertIn("own", r.get_json()["error"])

    def test_routes_of_a_stranger_look_like_a_missing_user(self):
        stranger = self.ann.get(f"/api/mates/{self.bob_id}/routes")
        missing = self.ann.get("/api/mates/999/routes")
        self.assertEqual(stranger.status_code, 404)
        self.assertEqual(stranger.get_json(), missing.get_json())
        self.post("/api/mates/request", {"username": "bob"}, self.ann)
        self.assertEqual(
            self.ann.get(f"/api/mates/{self.bob_id}/routes").status_code, 404)



class TestBadValues(WebCase):

    def add(self):
        return self.post("/api/history", {"date": "2024-03-09", "from": "ATL",
                                          "to": "LHR"}).get_json()

    def test_wrong_typed_flight_fields_are_a_400_not_a_500(self):
        for body in ({"date": 20240309, "from": "ATL", "to": "LHR"},
                     {"date": "2024-03-09", "from": 5, "to": "LHR"},
                     {"date": "2024-03-09", "from": ["ATL"], "to": "LHR"},
                     {"date": "2024-03-09", "from": "ATL", "to": {"x": 1}}):
            r = self.post("/api/history", body)
            self.assertEqual(r.status_code, 400, body)
            self.assertIn("must be text", r.get_json()["error"])

    def test_an_id_that_is_not_a_whole_number_is_a_400(self):
        f = self.add()
        for bad in (True, "1", 1.5, None, [1]):
            r = self.post("/api/history/delete", {"id": bad})
            self.assertEqual(r.status_code, 400, repr(bad))
        r = self.client.post("/api/history/delete", data='{"id": Infinity}',
                             headers=ORIGIN, content_type="application/json")
        self.assertEqual(r.status_code, 400)
        # In particular `true` must not be read as id 1.
        self.assertEqual(self.client.get("/api/history").get_json()["flights"][0]["id"],
                         f["id"])

    def test_an_id_too_large_for_the_database_is_simply_missing(self):
        huge = 10 ** 30
        self.assertEqual(self.post("/api/history/delete", {"id": huge}).get_json(),
                         {"removed": False})
        r = self.post("/api/history/update", {"id": huge, "date": "2024-03-09",
                                              "from": "ATL", "to": "LHR"})
        self.assertEqual((r.status_code, r.get_json()),
                         (404, {"error": "no such flight"}))
        for action in ("accept", "decline", "cancel", "remove"):
            self.assertEqual(self.post(f"/api/mates/{huge}/{action}").status_code,
                             404, action)
        self.assertEqual(self.client.get(f"/api/mates/{huge}/routes").status_code,
                         404)


class TestHostCheck(WebCase):

    def test_a_request_addressed_to_an_unknown_host_is_refused(self):
        evil = "http://evil.example:8817"
        r = self.client.get("/api/history", base_url=evil)
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/api/history", base_url=evil,
                             headers={"Origin": evil},
                             json={"date": "2024-03-09", "from": "ATL", "to": "LHR"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get("/api/history").get_json()["flights"], [])

    def test_local_names_and_the_configured_host_are_accepted(self):
        for base in ("http://localhost:8817", "http://127.0.0.1:8817",
                     "http://[::1]:8817"):
            self.assertEqual(self.client.get("/api/me", base_url=base).status_code,
                             200, base)
        app = create_app(Config(data_dir=self.dir, live=False,
                                base_url="https://wingmates.example"),
                         airports=self.airports)
        r = app.test_client().get("/api/me", base_url="https://wingmates.example")
        self.assertEqual(r.status_code, 200)


class TestHealth(WebCase):
    INTERNAL = "http://10.214.3.7:10000"

    def test_it_answers_whatever_host_the_checker_uses(self):
        r = self.client.get("/healthz", base_url=self.INTERNAL)
        self.assertEqual((r.status_code, r.get_json()), (200, {"ok": True}))
        # Only the health check is exempt from the host allow-list.
        self.assertEqual(
            self.client.get("/api/me", base_url=self.INTERNAL).status_code, 403)
        self.assertEqual(self.client.get("/", base_url=self.INTERNAL).status_code,
                         403)

    def test_it_reports_a_missing_database_without_creating_one(self):
        (self.dir / "flights.db").unlink()
        r = self.client.get("/healthz")
        self.assertEqual((r.status_code, r.get_json()), (503, {"ok": False}))
        self.assertFalse((self.dir / "flights.db").exists())

    def test_it_only_answers_get(self):
        self.assertEqual(self.post("/healthz").status_code, 405)


class TestBodyCap(WebCase):
    """On a shared site one signed-in person must not be able to exhaust the
    server's memory or the disk everyone shares with a single request."""

    ROW = "2024-03-09,ATL,LHR\n"

    def test_an_oversized_request_is_refused(self):
        big = "date,from,to\n" + self.ROW * 200_000          # about 3.8 MB
        r = self.post("/api/history/import", {"csv": big})
        self.assertEqual(r.status_code, 413)
        self.assertIn("error", r.get_json())
        self.assertEqual(self.client.get("/api/history").get_json()["flights"], [])

    def test_a_long_real_history_still_fits(self):
        rows = "".join(f"20{y:02d}-{m:02d}-15,ATL,LHR\n"
                       for y in range(0, 26) for m in range(1, 13)) * 10
        r = self.post("/api/history/import", {"csv": "date,from,to\n" + rows})
        self.assertEqual((r.status_code, r.get_json()["added"]), (200, 312))


if __name__ == "__main__":
    unittest.main(verbosity=2)
