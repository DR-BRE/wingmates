"""Mates store tests: requests, pairs, and what one user may see of another."""
import sys
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.db import connect
from fc.mates import MAX_REQUESTS, Mates
from tests.helpers import stores

PERSON = {"id", "username", "name", "picture_url"}
PRIVATE = {"email", "date", "airline", "flight_number", "aircraft", "seat",
           "notes", "google_sub", "count", "times"}


def keys(obj):
    """Every dict key anywhere inside obj."""
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in keys(v)}
    return set()


class MatesCase(unittest.TestCase):
    def setUp(self):
        self.dir, self.airports, self.history, self.users = stores(self)
        self.mates = Mates(self.users, self.history)
        self.ann = self.users.create("Ann", "ann")["id"]
        self.bob = self.users.create("Bob", "bob")["id"]

    def rel(self, viewer, username):
        return self.mates.card(viewer, username)["relation"]

    def befriend(self, a, a_name, b, b_name):
        self.mates.request(a, b_name)
        self.assertTrue(self.mates.accept(b, a))


class TestCard(MatesCase):

    def test_card_has_only_the_lookup_fields(self):
        self.history.for_user(self.bob).add("2024-03-09", "ATL", "LHR")
        card = self.mates.card(self.ann, "bob")
        self.assertEqual(set(card), PERSON | {"relation"})
        self.assertEqual(card["relation"], "none")

    def test_lookup_is_exact_but_forgiving_about_typing(self):
        self.assertEqual(self.mates.card(self.ann, "@Bob ")["id"], self.bob)
        self.assertIsNone(self.mates.card(self.ann, "bo"))
        self.assertIsNone(self.mates.card(self.ann, "nobody"))

    def test_relation_in_each_state(self):
        self.assertEqual(self.rel(self.ann, "ann"), "self")
        self.assertEqual(self.rel(self.ann, "bob"), "none")
        self.mates.request(self.ann, "bob")
        self.assertEqual(self.rel(self.ann, "bob"), "requested")
        self.assertEqual(self.rel(self.bob, "ann"), "incoming")
        self.mates.accept(self.bob, self.ann)
        self.assertEqual(self.rel(self.ann, "bob"), "mate")
        self.assertEqual(self.rel(self.bob, "ann"), "mate")


class TestRequests(MatesCase):

    def test_request_then_accept_is_visible_from_both_sides(self):
        self.assertEqual(self.mates.request(self.ann, "bob")["relation"],
                         "requested")
        s = self.mates.social(self.bob)
        self.assertEqual([p["username"] for p in s["incoming"]], ["ann"])
        self.assertEqual(self.mates.social(self.ann)["outgoing"][0]["username"],
                         "bob")
        self.assertTrue(self.mates.accept(self.bob, self.ann))
        for uid, other in ((self.ann, "bob"), (self.bob, "ann")):
            s = self.mates.social(uid)
            self.assertEqual([m["username"] for m in s["mates"]], [other])
            self.assertEqual((s["incoming"], s["outgoing"]), ([], []))

    def test_only_the_recipient_can_accept(self):
        self.mates.request(self.ann, "bob")
        self.assertFalse(self.mates.accept(self.ann, self.bob))
        self.assertFalse(self.mates.accept(self.bob, 999))
        self.assertEqual(self.rel(self.ann, "bob"), "requested")

    def test_crossing_requests_make_mates_at_once(self):
        self.mates.request(self.ann, "bob")
        self.assertEqual(self.mates.request(self.bob, "ann")["relation"], "mate")
        self.assertEqual(self.mates.social(self.ann)["outgoing"], [])

    def test_asking_twice_changes_nothing(self):
        self.mates.request(self.ann, "bob")
        self.mates.request(self.ann, "bob")
        self.assertEqual(len(self.mates.social(self.bob)["incoming"]), 1)

    def test_decline_is_silent_and_blocks_a_second_request(self):
        self.mates.request(self.ann, "bob")
        self.assertTrue(self.mates.decline(self.bob, self.ann))
        self.assertFalse(self.mates.decline(self.bob, self.ann))
        self.assertEqual(self.mates.social(self.bob)["incoming"], [])
        # Ann is not told: it still reads as requested, before and after retrying.
        self.assertEqual(self.rel(self.ann, "bob"), "requested")
        self.assertEqual(self.mates.request(self.ann, "bob")["relation"],
                         "requested")
        self.assertEqual(self.mates.social(self.bob)["incoming"], [])
        self.assertEqual(self.rel(self.bob, "ann"), "none")

    def test_the_decliner_can_still_add_them_later(self):
        self.mates.request(self.ann, "bob")
        self.mates.decline(self.bob, self.ann)
        self.assertEqual(self.mates.request(self.bob, "ann")["relation"], "mate")

    def test_cancel_of_a_pending_request_allows_a_new_one(self):
        self.mates.request(self.ann, "bob")
        self.assertTrue(self.mates.cancel(self.ann, self.bob))
        self.assertFalse(self.mates.cancel(self.ann, self.bob))
        self.assertEqual(self.mates.social(self.bob)["incoming"], [])
        self.mates.request(self.ann, "bob")
        self.assertEqual(len(self.mates.social(self.bob)["incoming"]), 1)

    def test_cancel_of_a_declined_request_keeps_the_block(self):
        self.mates.request(self.ann, "bob")
        self.mates.decline(self.bob, self.ann)
        self.assertTrue(self.mates.cancel(self.ann, self.bob))
        self.assertEqual(self.rel(self.ann, "bob"), "none")
        self.assertEqual(self.mates.social(self.ann)["outgoing"], [])
        self.assertEqual(self.mates.request(self.ann, "bob")["relation"],
                         "requested")
        self.assertEqual(self.mates.social(self.bob)["incoming"], [])

    def test_after_a_withdrawn_request_the_other_side_must_ask_normally(self):
        self.mates.request(self.ann, "bob")
        self.mates.decline(self.bob, self.ann)
        self.mates.cancel(self.ann, self.bob)
        # Ann took her request back, so Bob adding her must not skip her consent.
        self.assertEqual(self.mates.request(self.bob, "ann")["relation"],
                         "requested")
        self.assertEqual(self.rel(self.ann, "bob"), "incoming")

    def test_refusals(self):
        with self.assertRaises(LookupError):
            self.mates.request(self.ann, "nobody")
        with self.assertRaises(ValueError) as cm:
            self.mates.request(self.ann, "@Ann")
        self.assertIn("own", str(cm.exception))
        self.befriend(self.ann, "ann", self.bob, "bob")
        with self.assertRaises(ValueError) as cm:
            self.mates.request(self.ann, "bob")
        self.assertIn("already", str(cm.exception))

    def test_requests_are_capped(self):
        for i in range(MAX_REQUESTS):
            self.users.create(f"U{i}", f"user_{i}")
            self.mates.request(self.ann, f"user_{i}")
        with self.assertRaises(ValueError) as cm:
            self.mates.request(self.ann, "bob")
        self.assertIn(str(MAX_REQUESTS), str(cm.exception))
        # A declined request still counts, so the cap cannot be used to learn
        # which requests were declined.
        self.mates.decline(self.users.by_username("user_0")["id"], self.ann)
        with self.assertRaises(ValueError):
            self.mates.request(self.ann, "bob")
        # Answering someone's request to you is not a new request.
        self.mates.request(self.bob, "ann")
        self.assertEqual(self.mates.request(self.ann, "bob")["relation"], "mate")


class TestMates(MatesCase):

    def test_either_side_can_remove_and_a_new_request_is_then_allowed(self):
        self.befriend(self.ann, "ann", self.bob, "bob")
        self.assertTrue(self.mates.remove(self.bob, self.ann))
        self.assertFalse(self.mates.remove(self.ann, self.bob))
        self.assertEqual(self.mates.social(self.ann)["mates"], [])
        self.assertEqual(self.mates.request(self.ann, "bob")["relation"],
                         "requested")

    def test_deleting_a_user_clears_their_requests_and_pairs(self):
        cy = self.users.create("Cy", "cy_")["id"]
        self.befriend(self.ann, "ann", self.bob, "bob")
        self.mates.request(cy, "ann")
        self.users.delete(self.bob)
        self.users.delete(cy)
        s = self.mates.social(self.ann)
        self.assertEqual((s["mates"], s["incoming"], s["outgoing"]), ([], [], []))

    def test_mates_are_ranked_by_wingspan(self):
        cy = self.users.create("Cy", "cy_")["id"]
        self.befriend(self.ann, "ann", self.bob, "bob")
        self.befriend(self.ann, "ann", cy, "cy_")
        self.history.for_user(self.bob).add("2024-01-01", "ATL", "JFK")
        self.history.for_user(cy).add("2024-01-01", "ATL", "NRT")
        s = self.mates.social(self.ann)
        self.assertEqual([m["username"] for m in s["mates"]], ["cy_", "bob"])
        self.assertEqual(s["me"]["stats"]["distance_mi"], 0)


class TestPrivacy(MatesCase):

    def setUp(self):
        super().setUp()
        h = self.history.for_user(self.bob)
        for day in ("2024-03-09", "2024-04-09", "2024-05-09"):
            h.add(day, "LHR", "ATL", airline="Delta", flight_number="DL31",
                  aircraft="A333", seat="34A", notes="secret")
        h.add("2024-03-16", "ATL", "LHR")
        h.add("2024-06-01", "ATL", "JFK")

    def test_social_payload_has_exactly_the_allowed_fields(self):
        self.befriend(self.ann, "ann", self.bob, "bob")
        s = self.mates.social(self.ann)
        mate = s["mates"][0]
        self.assertEqual(set(mate), PERSON | {"stats"})
        self.assertEqual(set(mate["stats"]), {"flights", "distance_mi",
                                              "distance_km", "airports",
                                              "countries"})
        self.assertEqual(mate["stats"]["flights"], 5)
        self.assertEqual(keys(s) & PRIVATE, set())

    def test_routes_are_distinct_undirected_and_bare(self):
        self.befriend(self.ann, "ann", self.bob, "bob")
        routes = self.mates.routes(self.ann, self.bob)
        # Four ATL-LHR flights in both directions collapse to one route, always
        # listed alphabetically so the direction flown is not revealed.
        self.assertEqual([(r["from"]["iata"], r["to"]["iata"]) for r in routes],
                         [("ATL", "JFK"), ("ATL", "LHR")])
        self.assertEqual(set(routes[0]), {"from", "to"})
        self.assertEqual(set(routes[0]["from"]),
                         {"iata", "name", "city", "country", "lat", "lon"})
        self.assertEqual(keys(routes) & PRIVATE, set())

    def test_routes_are_refused_unless_mates(self):
        self.assertIsNone(self.mates.routes(self.ann, self.bob))
        self.mates.request(self.ann, "bob")
        self.assertIsNone(self.mates.routes(self.ann, self.bob))
        self.assertIsNone(self.mates.routes(self.bob, self.ann))
        self.assertIsNone(self.mates.routes(self.ann, 999))
        self.assertIsNone(self.mates.routes(self.ann, self.ann))

    def test_a_flight_with_an_unknown_airport_is_skipped_not_fatal(self):
        with closing(connect(self.history.path)) as db, db:
            db.execute("INSERT INTO flights (user_id, date, origin, dest,"
                       " distance_km, created_at) VALUES (?,?,?,?,?,?)",
                       (self.bob, "2025-01-01", "ZZZ", "ATL", 500.0, "t"))
        self.befriend(self.ann, "ann", self.bob, "bob")
        self.assertEqual(self.mates.social(self.ann)["mates"][0]["stats"]["flights"], 6)
        self.assertEqual(len(self.mates.routes(self.ann, self.bob)), 2)



class TestDeclineStaysSecret(MatesCase):
    """A sender must not be able to tell a declined request from an unanswered
    one, whatever they do next."""

    def test_re_sending_a_withdrawn_request_still_obeys_the_cap(self):
        self.mates.request(self.ann, "bob")
        self.mates.decline(self.bob, self.ann)
        self.mates.cancel(self.ann, self.bob)
        for i in range(MAX_REQUESTS):
            self.users.create(f"U{i}", f"user_{i}")
            self.mates.request(self.ann, f"user_{i}")
        with self.assertRaises(ValueError) as cm:
            self.mates.request(self.ann, "bob")
        self.assertIn(str(MAX_REQUESTS), str(cm.exception))
        self.assertEqual(len(self.mates.social(self.ann)["outgoing"]),
                         MAX_REQUESTS)

    def test_a_re_sent_request_is_listed_as_newest_either_way(self):
        self.users.create("Cy", "cy_")
        orders = []
        for declined in (False, True):
            ann = self.users.create("A", f"ann_{int(declined)}")["id"]
            bob = self.users.create("B", f"bob_{int(declined)}")
            self.mates.request(ann, bob["username"])
            self.mates.request(ann, "cy_")
            if declined:
                self.mates.decline(bob["id"], ann)
            self.mates.cancel(ann, bob["id"])
            self.mates.request(ann, bob["username"])
            orders.append([p["name"] for p in
                           self.mates.social(ann)["outgoing"]])
        self.assertEqual(orders, [["B", "Cy"], ["B", "Cy"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
