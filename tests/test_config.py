"""Config tests: settings come from a mapping, never the real environment."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.config import Config


class TestConfig(unittest.TestCase):

    def test_defaults_are_local_with_live_on(self):
        c = Config.from_env({})
        self.assertEqual((c.auth, c.live, c.dev_users), ("local", True, False))
        self.assertEqual(c.db_path, Path.home() / ".wingmates" / "flights.db")
        self.assertEqual(c.base_url, "http://localhost:8817")
        self.assertIsNone(c.secret_key)

    def test_settings_are_read_from_the_mapping(self):
        c = Config.from_env({
            "WINGMATES_LIVE": "0", "WINGMATES_DEV_USERS": "1",
            "WINGMATES_DATA_DIR": "/tmp/wm", "SECRET_KEY": "s3",
            "WINGMATES_BASE_URL": "https://wingmates.example/"})
        self.assertEqual((c.live, c.dev_users), (False, True))
        self.assertEqual(c.db_path, Path("/tmp/wm/flights.db"))
        self.assertEqual(c.base_url, "https://wingmates.example")
        self.assertEqual(c.secret_key, "s3")

    def test_a_flag_that_is_not_0_or_1_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            Config.from_env({"WINGMATES_LIVE": "yes"})
        self.assertIn("WINGMATES_LIVE", str(cm.exception))

    def test_an_auth_mode_other_than_local_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            Config.from_env({"WINGMATES_AUTH": "google"})
        self.assertIn("WINGMATES_AUTH", str(cm.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
