"""The store and sign-in suites again, with Turso as the database.

Every test class listed here is re-run with `on_turso = True`, which makes the
shared fixtures hand out a Turso database served by the stand-in. The tests
themselves are unchanged: what passes on a SQLite file must pass on Turso.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.turso import Turso
from tests import test_history, test_mates, test_signin, test_users

SUITES = {
    test_users: ["TestUsers", "TestGoogleAccounts", "TestSetUsername",
                 "TestSessionEpoch"],
    test_history: ["TestAdd", "TestUpdate", "TestStats", "TestImport",
                   "TestIsolation", "TestExport"],
    test_mates: ["TestCard", "TestRequests", "TestMates", "TestPrivacy",
                 "TestDeclineStaysSecret"],
    test_signin: ["TestSignIn", "TestSessions", "TestAccountDelete",
                  "TestTwoPeople"],
}

for module, names in SUITES.items():
    for name in names:
        globals()[f"{name}OnTurso"] = type(
            f"{name}OnTurso", (getattr(module, name),), {"on_turso": True})


class TestTheFixtureReallyUsesTurso(unittest.TestCase):
    on_turso = True

    def test_requests_reach_the_stand_in_and_no_file_is_made(self):
        from tests.helpers import stores
        d, _, history, users = stores(self)
        self.assertIsInstance(self.database, Turso)
        uid = users.create("Ann", "ann")["id"]
        history.for_user(uid).add("2024-03-09", "ATL", "LHR")
        self.assertGreater(len(self.fake.calls), 0)
        self.assertFalse((d / "flights.db").exists())


class TestImportIsBatchedOnTurso(test_history.HistoryCase):
    on_turso = True

    def test_a_large_import_takes_a_handful_of_requests(self):
        days = [f"2024-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 29)]
        text = "date,from,to\n" + "".join(f"{day},ATL,LHR\n" for day in days)
        self.fake.calls.clear()
        self.assertEqual(self.h.import_csv(text)["added"], len(days))   # 336 rows
        # One read for existing flights, two batches of inserts, one commit.
        self.assertLessEqual(len(self.fake.calls), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
