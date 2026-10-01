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


if __name__ == "__main__":
    unittest.main(verbosity=2)
