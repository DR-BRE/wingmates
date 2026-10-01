"""State-machine tests. Fully offline — synthetic positions, no network.

The point of these is the hysteresis: a flight tracker that fires "Departed" on
a single spurious ground-bit flip is worse than useless, because the one thing
the product sells is that its alerts are trustworthy.
"""
import sys
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.schema import EventType, FlightKey, FlightState, Phase, Position, Vertical
from fc.statemachine import CONFIRM, STALE_AFTER, apply, check_stale

KEY = FlightKey("DAL983", date(2026, 9, 23))
T0 = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def pos(t_offset=0, **kw):
    t = T0 + timedelta(seconds=t_offset)
    return Position(key=KEY, source="test", observed_at=t, received_at=t, **kw)


def feed(st, positions):
    out = []
    for p in positions:
        out += apply(st, p)
    return [e.type for e in out]


def gate(t=0):
    return pos(t, on_ground=True, ground_speed_kt=0.0, lat=33.64, lon=-84.43)


def taxi(t=0, gs=15.0):
    return pos(t, on_ground=True, ground_speed_kt=gs, lat=33.64, lon=-84.43)


def air(t=0, alt=5000, gs=250.0, vs=2000):
    return pos(t, on_ground=False, altitude_ft=alt, ground_speed_kt=gs,
               vertical_rate_fpm=vs, lat=33.7, lon=-84.5)


class TestDepartureSequence(unittest.TestCase):

    def test_gate_to_airborne_emits_pushback_then_departed(self):
        st = FlightState(key=KEY)
        types = feed(st, [gate(0), taxi(30), air(60), air(90)])
        self.assertIn(EventType.PUSHBACK, types)
        self.assertIn(EventType.DEPARTED, types)
        self.assertLess(types.index(EventType.PUSHBACK),
                        types.index(EventType.DEPARTED))
        self.assertIs(st.phase, Phase.AIRBORNE)

    def test_first_sample_emits_acquired_exactly_once(self):
        st = FlightState(key=KEY)
        types = feed(st, [gate(0), gate(30), gate(60)])
        self.assertEqual(types.count(EventType.ACQUIRED), 1)


class TestHysteresis(unittest.TestCase):

    def test_single_spurious_airborne_sample_does_not_emit_departed(self):
        """The bug that makes a tracker untrustworthy: ADS-B drops the ground
        bit for one sample while the aircraft is still on the taxiway."""
        st = FlightState(key=KEY)
        types = feed(st, [gate(0), taxi(30), air(60), taxi(90), taxi(120)])
        self.assertNotIn(EventType.DEPARTED, types)
        self.assertIs(st.phase, Phase.TAXI_OUT)

    def test_sustained_airborne_does_emit_departed(self):
        st = FlightState(key=KEY)
        types = feed(st, [gate(0), taxi(30)]
                     + [air(60 + 30 * i) for i in range(CONFIRM)])
        self.assertIn(EventType.DEPARTED, types)

    def test_spurious_ground_sample_midflight_does_not_emit_landed(self):
        st = FlightState(key=KEY)
        feed(st, [air(0, alt=35000, vs=0), air(30, alt=35000, vs=0)])
        types = feed(st, [taxi(60), air(90, alt=35000, vs=0)])
        self.assertNotIn(EventType.LANDED, types)
        self.assertIs(st.phase, Phase.AIRBORNE)


class TestArrivalSequence(unittest.TestCase):

    def test_landing_then_on_block(self):
        st = FlightState(key=KEY)
        feed(st, [air(0), air(30)])
        types = feed(st, [taxi(60), taxi(90), gate(120), gate(150)])
        self.assertIn(EventType.LANDED, types)
        self.assertIn(EventType.ON_BLOCK, types)
        self.assertIs(st.phase, Phase.ARRIVED)

    def test_arrived_is_distinguished_from_at_gate(self):
        """Same physical reading — stopped on the ground — but a flight that has
        flown is ARRIVED, not waiting to depart."""
        st = FlightState(key=KEY)
        feed(st, [air(0), air(30), taxi(60), taxi(90), gate(120), gate(150)])
        self.assertTrue(st.has_been_airborne)
        self.assertIs(st.phase, Phase.ARRIVED)

        fresh = FlightState(key=KEY)
        feed(fresh, [gate(0)])
        self.assertIs(fresh.phase, Phase.AT_GATE)


class TestVerticalProfile(unittest.TestCase):

    def test_top_of_climb_only_above_cruise_altitude(self):
        st = FlightState(key=KEY)
        feed(st, [air(0, alt=30000, vs=1500), air(30, alt=30000, vs=1500)])
        types = feed(st, [air(60, alt=35000, vs=0)])
        self.assertIn(EventType.TOP_OF_CLIMB, types)

    def test_low_level_levelling_is_not_top_of_climb(self):
        st = FlightState(key=KEY)
        feed(st, [air(0, alt=3000, vs=1500), air(30, alt=3000, vs=1500)])
        types = feed(st, [air(60, alt=4000, vs=0)])
        self.assertNotIn(EventType.TOP_OF_CLIMB, types)

    def test_descent_started_fires_from_cruise(self):
        st = FlightState(key=KEY)
        feed(st, [air(0, alt=35000, vs=0), air(30, alt=35000, vs=0)])
        types = feed(st, [air(60, alt=34000, vs=-1800)])
        self.assertIn(EventType.DESCENT_STARTED, types)
        self.assertIs(st.vertical, Vertical.DESCENT)

    def test_altitude_milestones_fire_once_each(self):
        st = FlightState(key=KEY)
        types = feed(st, [air(30 * i, alt=a, vs=2000) for i, a in
                          enumerate([2000, 11000, 12000, 19000, 20000, 31000])])
        self.assertEqual(types.count(EventType.ALTITUDE_MILESTONE), 3)


class TestEmergency(unittest.TestCase):

    def test_emergency_squawk_fires_on_first_sample(self):
        """No hysteresis here — a delayed 7700 alert is worthless."""
        st = FlightState(key=KEY)
        types = feed(st, [air(0, alt=35000, vs=0)])
        self.assertNotIn(EventType.EMERGENCY_SQUAWK, types)
        types = feed(st, [pos(30, on_ground=False, altitude_ft=35000,
                              squawk="7700")])
        self.assertIn(EventType.EMERGENCY_SQUAWK, types)

    def test_emergency_is_loud(self):
        st = FlightState(key=KEY)
        apply(st, air(0))
        events = apply(st, pos(30, on_ground=False, altitude_ft=35000,
                               squawk="7600"))
        emerg = [e for e in events if e.type is EventType.EMERGENCY_SQUAWK]
        self.assertTrue(emerg and emerg[0].loud)

    def test_ordinary_squawk_change_is_not_an_emergency(self):
        st = FlightState(key=KEY)
        apply(st, pos(0, on_ground=False, altitude_ft=35000, squawk="1200"))
        types = [e.type for e in
                 apply(st, pos(30, on_ground=False, altitude_ft=35000,
                               squawk="2275"))]
        self.assertIn(EventType.SQUAWK_CHANGED, types)
        self.assertNotIn(EventType.EMERGENCY_SQUAWK, types)


class TestSignalLoss(unittest.TestCase):

    def test_stale_flight_reports_signal_lost(self):
        st = FlightState(key=KEY)
        apply(st, air(0))
        self.assertEqual(check_stale(st, T0 + timedelta(minutes=1)), [])
        events = check_stale(st, T0 + STALE_AFTER + timedelta(minutes=1))
        self.assertEqual([e.type for e in events], [EventType.SIGNAL_LOST])
        self.assertIs(st.phase, Phase.SIGNAL_LOST)

    def test_reacquisition_emits_an_event(self):
        st = FlightState(key=KEY)
        apply(st, air(0))
        check_stale(st, T0 + STALE_AFTER + timedelta(minutes=1))
        types = [e.type for e in apply(st, air(600))]
        self.assertIn(EventType.SIGNAL_REACQUIRED, types)

    def test_signal_loss_is_not_reported_for_arrived_flights(self):
        st = FlightState(key=KEY)
        feed(st, [air(0), air(30), taxi(60), taxi(90), gate(120), gate(150)])
        self.assertEqual(check_stale(st, T0 + timedelta(hours=2)), [])


class TestStateAccumulation(unittest.TestCase):

    def test_maxima_and_trail_accumulate(self):
        st = FlightState(key=KEY)
        feed(st, [air(0, alt=10000, gs=300), air(30, alt=35000, gs=480),
                  air(60, alt=30000, gs=400)])
        self.assertEqual(st.max_altitude_ft, 35000)
        self.assertEqual(st.max_speed_kt, 480)
        self.assertEqual(len(st.trail), 1)      # same coords -> deduped

    def test_identity_is_enriched_by_later_samples(self):
        """The first sample often lacks registration; a later one carries it."""
        st = FlightState(key=KEY)
        apply(st, air(0))
        self.assertIsNone(st.registration)
        apply(st, pos(30, on_ground=False, altitude_ft=35000,
                      registration="N695DL", aircraft_type="B752"))
        self.assertEqual(st.registration, "N695DL")
        self.assertEqual(st.aircraft_type, "B752")

    def test_serialisation_round_trips(self):
        st = FlightState(key=KEY)
        feed(st, [gate(0), taxi(30), air(60), air(90)])
        j = st.to_json()
        self.assertEqual(j["callsign"], "DAL983")
        self.assertEqual(j["phase"], "airborne")
        self.assertIsInstance(j["trail"], list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
