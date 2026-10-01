"""Sign-in helper tests. Offline: nothing here contacts Google."""
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.auth import persistent_key, safe_next


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
