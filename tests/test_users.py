"""User store tests. Offline: a temp database."""
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.users import Users, normalize_username, validate_username
from tests.helpers import database, temp_dir


class TestUsernameRules(unittest.TestCase):

    def test_input_is_trimmed_unprefixed_and_lowercased(self):
        self.assertEqual(normalize_username("  @Brett "), "brett")
        self.assertEqual(validate_username("@Brett_99"), "brett_99")
        self.assertEqual(normalize_username(None), "")

    def test_malformed_names_are_refused(self):
        for bad in ("ab", "a" * 21, "has space", "dash-ed", "émile", "", None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                validate_username(bad)

    def test_length_limits_are_inclusive(self):
        self.assertEqual(validate_username("abc"), "abc")
        self.assertEqual(validate_username("a" * 20), "a" * 20)

    def test_reserved_names_are_refused(self):
        for bad in ("admin", "Wingmates", "support", "you"):
            with self.assertRaises(ValueError) as cm:
                validate_username(bad)
            self.assertIn("reserved", str(cm.exception))


class UsersCase(unittest.TestCase):
    def setUp(self):
        self.users = Users(database(self, temp_dir(self)))


class TestUsers(UsersCase):

    def test_create_returns_only_public_fields(self):
        u = self.users.create("Ann Lee", "Ann", email="ann@example.com")
        self.assertEqual(set(u), {"id", "username", "name", "picture_url"})
        self.assertEqual((u["username"], u["name"]), ("ann", "Ann Lee"))
        self.assertEqual(self.users.get(u["id"]), u)

    def test_a_taken_username_is_refused_whatever_its_case(self):
        self.users.create("Ann", "ann")
        with self.assertRaises(ValueError) as cm:
            self.users.create("Other", "ANN")
        self.assertIn("taken", str(cm.exception))

    def test_lookup_accepts_the_way_people_type_usernames(self):
        u = self.users.create("Brett", "brett")
        self.assertEqual(self.users.by_username("@Brett "), u)
        self.assertIsNone(self.users.by_username("bret"))
        self.assertIsNone(self.users.by_username(""))

    def test_local_user_is_created_once(self):
        a, b = self.users.ensure_local(), self.users.ensure_local()
        self.assertEqual(a, b)
        self.assertEqual((a["username"], a["name"]), ("you", "You"))

    def test_a_deleted_users_name_can_be_taken_again(self):
        u = self.users.create("Ann", "ann")
        self.assertTrue(self.users.delete(u["id"]))
        self.assertFalse(self.users.delete(u["id"]))
        self.assertIsNone(self.users.get(u["id"]))
        self.assertNotEqual(self.users.create("New Ann", "ann")["id"], u["id"])


    def test_deleting_a_user_removes_their_rows_without_database_cascades(self):
        from contextlib import closing
        from fc.db import connect
        ann = self.users.create("Ann", "ann")["id"]
        bob = self.users.create("Bob", "bob")["id"]
        with closing(connect(self.users.database)) as db, db:
            db.execute("INSERT INTO flights (user_id, date, origin, dest,"
                       " distance_km, created_at) VALUES (?,?,?,?,?,?)",
                       (ann, "2024-03-09", "ATL", "LHR", 6760.0, "t"))
            db.execute("INSERT INTO flights (user_id, date, origin, dest,"
                       " distance_km, created_at) VALUES (?,?,?,?,?,?)",
                       (bob, "2024-03-09", "ATL", "JFK", 1200.0, "t"))
            db.execute("INSERT INTO mate_requests (from_id, to_id, status,"
                       " created_at) VALUES (?, ?, 'pending', 't')", (bob, ann))
            db.execute("INSERT INTO mates (user_lo, user_hi, created_at)"
                       " VALUES (?, ?, 't')", (min(ann, bob), max(ann, bob)))
        self.assertTrue(self.users.delete(ann))
        with closing(connect(self.users.database)) as db:
            counts = [db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("flights", "mate_requests", "mates", "users")]
        self.assertEqual(counts, [1, 0, 0, 1])


class TestGoogleAccounts(UsersCase):

    def google(self, sub="g-1", email="brett@example.com", name="Brett F",
               picture_url="https://img.example/b.png"):
        return self.users.upsert_google(sub, email, name, picture_url)

    def test_first_sign_in_creates_an_account_without_a_username(self):
        u = self.google()
        self.assertEqual(set(u), {"id", "username", "name", "picture_url"})
        self.assertEqual((u["username"], u["name"], u["picture_url"]),
                         (None, "Brett F", "https://img.example/b.png"))

    def test_later_sign_ins_refresh_the_profile_and_keep_the_account(self):
        first = self.google()
        self.users.set_username(first["id"], "brett")
        again = self.google(email="new@example.com", name="Brett Francoeur",
                            picture_url=None)
        self.assertEqual((again["id"], again["username"], again["name"],
                          again["picture_url"]),
                         (first["id"], "brett", "Brett Francoeur", None))

    def test_a_different_sub_is_a_different_account_even_with_the_same_email(self):
        self.assertNotEqual(self.google("g-1")["id"], self.google("g-2")["id"])

    def test_a_profile_without_a_name_gets_a_usable_one(self):
        self.assertEqual(self.google(name=None)["name"], "brett")
        self.assertEqual(self.google("g-2", email=None, name="  ")["name"],
                         "Wingmate")

    def test_an_account_without_a_username_cannot_be_looked_up(self):
        self.google()
        self.assertIsNone(self.users.by_username(""))
        self.assertIsNone(self.users.by_username("None"))


    def test_simultaneous_first_sign_ins_make_one_account(self):
        results, errors = [], []

        def sign_in():
            try:
                results.append(self.google("g-new")["id"])
            except Exception as e:                       # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=sign_in) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(results)), 1)


class TestSetUsername(UsersCase):

    def setUp(self):
        super().setUp()
        self.uid = self.users.upsert_google("g-1", "a@example.com", "A", None)["id"]

    def test_it_is_normalised_and_stored(self):
        self.assertEqual(self.users.set_username(self.uid, " @Brett ")["username"],
                         "brett")
        self.assertEqual(self.users.by_username("brett")["id"], self.uid)

    def test_it_can_only_be_set_once(self):
        self.users.set_username(self.uid, "brett")
        with self.assertRaises(ValueError) as cm:
            self.users.set_username(self.uid, "other")
        self.assertIn("already", str(cm.exception))
        self.assertEqual(self.users.get(self.uid)["username"], "brett")

    def test_malformed_reserved_and_taken_names_are_refused(self):
        self.users.create("Ann", "ann")
        for bad, word in (("ab", "3 to 20"), ("admin", "reserved"),
                          ("ANN", "taken")):
            with self.assertRaises(ValueError) as cm:
                self.users.set_username(self.uid, bad)
            self.assertIn(word, str(cm.exception))
        self.assertIsNone(self.users.get(self.uid)["username"])

    def test_the_second_of_two_people_choosing_a_name_is_told_it_is_taken(self):
        other = self.users.upsert_google("g-2", "b@example.com", "B", None)["id"]
        self.users.set_username(other, "brett")
        with self.assertRaises(ValueError) as cm:
            self.users.set_username(self.uid, "brett")
        self.assertIn("taken", str(cm.exception))

    def test_a_missing_user_is_refused(self):
        with self.assertRaises(ValueError):
            self.users.set_username(999, "brett")


class TestSessionEpoch(UsersCase):

    def setUp(self):
        super().setUp()
        self.uid = self.users.create("Ann", "ann")["id"]

    def test_a_session_is_valid_only_under_the_current_epoch(self):
        self.assertEqual(self.users.session_epoch(self.uid), 0)
        self.assertEqual(self.users.for_session(self.uid, 0)["username"], "ann")
        self.users.end_sessions(self.uid)
        self.assertEqual(self.users.session_epoch(self.uid), 1)
        self.assertIsNone(self.users.for_session(self.uid, 0))
        self.assertEqual(self.users.for_session(self.uid, 1)["id"], self.uid)

    def test_a_missing_or_malformed_epoch_never_matches(self):
        for bad in (None, "0", 0.5, [0]):
            self.assertIsNone(self.users.for_session(self.uid, bad), repr(bad))
        self.assertIsNone(self.users.for_session(999, 0))
        self.assertIsNone(self.users.session_epoch(999))

    def test_the_epoch_is_not_part_of_the_public_user(self):
        self.assertNotIn("session_epoch", self.users.for_session(self.uid, 0))

    def test_ending_one_persons_sessions_leaves_others_alone(self):
        bob = self.users.create("Bob", "bob")["id"]
        self.users.end_sessions(self.uid)
        self.assertEqual(self.users.session_epoch(bob), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
