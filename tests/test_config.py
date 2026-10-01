"""Config tests: settings come from a mapping, never the real environment."""
import json
import sys
import tempfile
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

    def test_an_unknown_auth_mode_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            Config.from_env({"WINGMATES_AUTH": "ldap"})
        self.assertIn("WINGMATES_AUTH", str(cm.exception))

    def google_env(self, **extra):
        return {"WINGMATES_AUTH": "google", "GOOGLE_CLIENT_ID": "id-1",
                "GOOGLE_CLIENT_SECRET": "shh", **extra}

    def test_google_mode_reads_the_client_from_the_environment(self):
        c = Config.from_env(self.google_env())
        self.assertEqual((c.auth, c.google_client_id, c.google_client_secret),
                         ("google", "id-1", "shh"))

    def test_google_mode_turns_live_off_and_ignores_dev_users(self):
        c = Config.from_env(self.google_env(WINGMATES_DEV_USERS="1"))
        self.assertEqual((c.live, c.dev_users), (False, False))
        self.assertTrue(Config.from_env(self.google_env(WINGMATES_LIVE="1")).live)

    def test_google_mode_falls_back_to_the_downloaded_client_file(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "google-client.json").write_text(json.dumps(
                {"web": {"client_id": "file-id", "client_secret": "file-shh"}}))
            c = Config.from_env({"WINGMATES_AUTH": "google",
                                 "WINGMATES_DATA_DIR": d})
        self.assertEqual((c.google_client_id, c.google_client_secret),
                         ("file-id", "file-shh"))

    def test_google_mode_without_a_client_refuses_to_start(self):
        with tempfile.TemporaryDirectory() as d:
            for content in (None, "not json", '{"installed": {}}', '[]'):
                if content is not None:
                    (Path(d) / "google-client.json").write_text(content)
                with self.assertRaises(ValueError) as cm:
                    Config.from_env({"WINGMATES_AUTH": "google",
                                     "WINGMATES_DATA_DIR": d})
                self.assertIn("GOOGLE_CLIENT_ID", str(cm.exception))
                self.assertIn("google-client.json", str(cm.exception))

    def test_secrets_are_not_in_the_repr(self):
        text = repr(Config.from_env(self.google_env(SECRET_KEY="key-material")))
        self.assertNotIn("shh", text)
        self.assertNotIn("key-material", text)

class TestBaseUrl(unittest.TestCase):

    def test_it_is_normalised(self):
        for raw, want in (("http://LocalHost:8817/", "http://localhost:8817"),
                          ("http://localhost:80", "http://localhost"),
                          ("HTTPS://Wing.Example:443", "https://wing.example"),
                          ("https://wing.example:8443", "https://wing.example:8443"),
                          ("http://[::1]:8817", "http://[::1]:8817")):
            self.assertEqual(Config(base_url=raw).base_url, want)
            self.assertEqual(
                Config.from_env({"WINGMATES_BASE_URL": raw}).base_url, want)

    def test_a_malformed_one_is_refused(self):
        for bad in ("localhost:8817", "ftp://localhost", "http://",
                    "http://user@localhost:8817", "http://localhost/app",
                    "http://localhost?x=1", "http://localhost:notaport", ""):
            with self.assertRaises(ValueError, msg=bad) as cm:
                Config(base_url=bad)
            self.assertIn("WINGMATES_BASE_URL", str(cm.exception))


    def test_on_render_it_defaults_to_the_services_own_address(self):
        render = {"RENDER_EXTERNAL_HOSTNAME": "wingmates-x1y2.onrender.com"}
        self.assertEqual(Config.from_env(render).base_url,
                         "https://wingmates-x1y2.onrender.com")
        both = {**render, "WINGMATES_BASE_URL": "https://wingmates.example"}
        self.assertEqual(Config.from_env(both).base_url,
                         "https://wingmates.example")

if __name__ == "__main__":
    unittest.main(verbosity=2)
