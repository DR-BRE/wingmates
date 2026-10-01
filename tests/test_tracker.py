"""Tracker persistence tests. Offline: a temp state file and no feed calls."""
import sys
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc import tracker as tracker_mod
from fc.schema import FlightKey, Position
from fc.statemachine import apply
from fc.tracker import Tracker


class TestRestart(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        for name, value in (("STATE_DIR", d), ("STATE_FILE", d / "state.json")):
            p = mock.patch.object(tracker_mod, name, value)
            p.start()
            self.addCleanup(p.stop)

    def _tracked(self, day):
        t = Tracker(feed=object())
        key = FlightKey("DAL554", day)
        at = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        st = tracker_mod.FlightState(key=key)
        t.flights[key] = st
        t._record(apply(st, Position(
            key=key, source="test", observed_at=at, received_at=at,
            lat=33.64, lon=-84.43, on_ground=False, altitude_ft=30000)))
        t.save()
        return key

    def test_alerts_survive_a_restart(self):
        self._tracked(datetime.now(UTC).date())
        again = Tracker(feed=object())
        self.assertEqual([e.title for e in again.alerts], ["Tracking started"])
        again.save()
        self.assertEqual(len(Tracker(feed=object()).alerts), 1)

    def test_flight_acquired_on_an_earlier_day_survives_a_restart(self):
        key = self._tracked(date(2026, 9, 26))
        self.assertIn(key, Tracker(feed=object()).flights)


if __name__ == "__main__":
    unittest.main(verbosity=2)
