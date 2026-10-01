"""Sign-in helper tests. Offline: nothing here contacts Google."""
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.auth import GoogleSignIn, persistent_key, safe_next


class TestSafeNext(unittest.TestCase):

    def test_a_path_on_this_site_is_kept(self):
        for ok in ("/", "/welcome", "/?tab=social", "/a/b?c=d#e"):
            self.assertEqual(safe_next(ok), ok)

    def test_anything_that_could_leave_the_site_becomes_the_home_page(self):
        for bad in ("https://evil.example", "//evil.example", "/\\evil.example",
                    "evil", "", None, 5, "/ok\nSet-Cookie: x", "/\tx",
                    "javascript:alert(1)"):
            self.assertEqual(safe_next(bad), "/", repr(bad))


class TestPersistentKey(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "data"

    def test_it_is_created_once_and_then_reused(self):
        first = persistent_key(self.dir)
        self.assertEqual(len(first), 64)
        self.assertEqual(persistent_key(self.dir), first)

    def test_the_file_is_readable_only_by_its_owner(self):
        persistent_key(self.dir)
        mode = stat.S_IMODE((self.dir / "secret_key").stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_an_empty_key_file_is_replaced(self):
        self.dir.mkdir(parents=True)
        (self.dir / "secret_key").write_text("")
        self.assertEqual(len(persistent_key(self.dir)), 64)


class Unrelated(Exception):
    """Stands for the JOSE library's errors, which share no base class with
    Authlib's own."""


class TestGoogleSignInFailsClosed(unittest.TestCase):
    """finish() is the gate: whatever goes wrong while completing a sign-in,
    the answer must be "nobody signed in", never a crash."""

    def setUp(self):
        self.app = Flask("signin-test")
        self.app.secret_key = "test-key"
        self.sign = GoogleSignIn(self.app, "id", "secret")

    def finish(self, **outcome):
        with self.app.test_request_context("/auth/callback?code=c&state=s"):
            with mock.patch.object(self.sign._oauth.google,
                                   "authorize_access_token", **outcome):
                return self.sign.finish()

    def test_any_failure_to_complete_is_nobody_signed_in(self):
        for exc in (Unrelated("bad signature"), requests.ConnectionError("down"),
                    requests.Timeout(), KeyError("id_token"), ValueError("junk")):
            with self.assertLogs(self.app.logger, "WARNING") as logs:
                self.assertIsNone(self.finish(side_effect=exc), type(exc).__name__)
            # The log names the kind of failure and nothing else.
            self.assertIn(type(exc).__name__, logs.output[0])
            self.assertNotIn(str(exc) or "~", logs.output[0])

    def test_a_token_without_a_subject_is_nobody_signed_in(self):
        self.assertIsNone(self.finish(return_value={}))
        self.assertIsNone(self.finish(return_value={"userinfo": {"email": "a@b.c"}}))

    def test_a_verified_profile_is_returned(self):
        info = {"sub": "g-1", "email": "a@b.c", "name": "A", "picture": "https://p/x"}
        self.assertEqual(self.finish(return_value={"userinfo": info}),
                         {"sub": "g-1", "email": "a@b.c", "name": "A",
                          "picture_url": "https://p/x"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
