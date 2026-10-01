"""User store tests. Offline: a temp database."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.users import Users, normalize_username, validate_username


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
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.users = Users(Path(tmp.name) / "flights.db")


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
