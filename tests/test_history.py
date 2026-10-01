"""Flight-history tests. Offline: a temp database and a four-airport fixture."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc.airports import Airports
from fc.history import History, great_circle_km, template_csv
from fc.users import Users

AIRPORTS_CSV = """iata,icao,name,city,country,lat,lon,size
ATL,KATL,Hartsfield Jackson Atlanta International Airport,Atlanta,US,33.6367,-84.4281,3
JFK,KJFK,John F. Kennedy International Airport,New York,US,40.6394,-73.7793,3
LHR,EGLL,London Heathrow Airport,London,GB,51.4707,-0.4599,3
LGW,EGKK,London Gatwick Airport,London,GB,51.1481,-0.1903,2
"""


class HistoryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        (d / "airports.csv").write_text(AIRPORTS_CSV)
        self.airports = Airports(d / "airports.csv")
        self.store = History(self.airports, d / "flights.db")
        self.users = Users(d / "flights.db")
        self.uid = self.users.create("Ann", "ann")["id"]
        self.h = self.store.for_user(self.uid)


class TestAirports(HistoryCase):

    def test_resolves_iata_and_icao_case_insensitively(self):
        self.assertEqual(self.airports.get("atl").iata, "ATL")
        self.assertEqual(self.airports.get("egll").iata, "LHR")
        self.assertIsNone(self.airports.get("ZZZ"))

    def test_search_puts_exact_code_first_then_larger_airports(self):
        self.assertEqual(self.airports.search("jfk")[0].iata, "JFK")
        self.assertEqual([a.iata for a in self.airports.search("london")],
                         ["LHR", "LGW"])


class TestAdd(HistoryCase):

    def test_add_stores_route_and_distance(self):
        f = self.h.add("2024-03-09", "atl", "LHR", airline="Delta",
                       flight_number="DL30")
        self.assertEqual((f["from"]["iata"], f["to"]["iata"]), ("ATL", "LHR"))
        self.assertEqual(f["flight_number"], "DL30")
        self.assertAlmostEqual(f["distance_mi"], 4200, delta=30)

    def test_icao_input_is_stored_as_iata(self):
        self.assertEqual(self.h.add("2024-03-09", "KATL", "EGLL")["from"]["iata"],
                         "ATL")

    def test_rejects_bad_input_with_a_reason(self):
        for args, word in ((("09/03/2024", "ATL", "LHR"), "YYYY-MM-DD"),
                           (("2024-03-09", "ZZZ", "LHR"), "ZZZ"),
                           (("2024-03-09", "ATL", "ATL"), "same")):
            with self.assertRaises(ValueError) as cm:
                self.h.add(*args)
            self.assertIn(word, str(cm.exception))
        self.assertEqual(self.h.list(), [])

    def test_list_is_newest_first_and_delete_removes(self):
        a = self.h.add("2020-01-01", "ATL", "JFK")
        b = self.h.add("2024-01-01", "JFK", "LHR")
        self.assertEqual([f["id"] for f in self.h.list()], [b["id"], a["id"]])
        self.assertTrue(self.h.delete(a["id"]))
        self.assertFalse(self.h.delete(a["id"]))
        self.assertEqual(len(self.h.list()), 1)

    def test_survives_reopening_the_database(self):
        self.h.add("2024-03-09", "ATL", "LHR")
        again = History(self.airports, self.h.path).for_user(self.uid)
        self.assertEqual(len(again.list()), 1)


class TestUpdate(HistoryCase):

    def test_update_changes_fields_and_recomputes_distance(self):
        f = self.h.add("2024-03-09", "ATL", "JFK", airline="Delta")
        g = self.h.update(f["id"], "2024-03-10", "ATL", "LHR",
                          flight_number="DL30")
        self.assertEqual((g["id"], g["date"], g["to"]["iata"]),
                         (f["id"], "2024-03-10", "LHR"))
        self.assertEqual(g["flight_number"], "DL30")
        self.assertEqual(g["airline"], "")        # omitted fields are cleared
        self.assertAlmostEqual(g["distance_mi"], 4200, delta=30)
        self.assertEqual(len(self.h.list()), 1)

    def test_update_validates_like_add_and_leaves_the_flight_alone(self):
        f = self.h.add("2024-03-09", "ATL", "JFK")
        with self.assertRaises(ValueError):
            self.h.update(f["id"], "2024-03-09", "ATL", "ZZZ")
        self.assertEqual(self.h.get(f["id"])["to"]["iata"], "JFK")

    def test_update_of_a_missing_flight_returns_none(self):
        self.assertIsNone(self.h.update(999, "2024-03-09", "ATL", "JFK"))


class TestStats(HistoryCase):

    def test_empty_history(self):
        s = self.h.stats()
        self.assertEqual((s["flights"], s["distance_mi"], s["longest"]),
                         (0, 0, None))

    def test_counts_distinct_airports_and_countries(self):
        self.h.add("2024-03-09", "ATL", "LHR")
        self.h.add("2024-03-16", "LHR", "ATL")
        self.h.add("2024-05-01", "ATL", "JFK")
        s = self.h.stats()
        self.assertEqual((s["flights"], s["airports"], s["countries"]), (3, 3, 2))
        self.assertEqual(s["longest"]["distance_mi"],
                         round(great_circle_km(33.6367, -84.4281,
                                               51.4707, -0.4599) / 1.609344))


class TestImport(HistoryCase):

    def test_template_header_round_trips_through_import(self):
        text = template_csv() + "2024-03-09,ATL,LHR,Delta,DL30,A333,34A,window\n"
        self.assertEqual(self.h.import_csv(text),
                         {"added": 1, "skipped": 0, "errors": []})
        f = self.h.list()[0]
        self.assertEqual((f["aircraft"], f["seat"], f["notes"]),
                         ("A333", "34A", "window"))

    def test_bad_rows_are_reported_by_line_and_good_rows_still_land(self):
        text = ("date,from,to\n"
                "2024-03-09,ATL,LHR\n"
                "March 9,ATL,LHR\n"
                "\n"
                "2024-03-10,ATL,XXX\n"
                "2024-03-11,LHR,JFK\n")
        r = self.h.import_csv(text)
        self.assertEqual((r["added"], r["skipped"]), (2, 0))
        self.assertEqual([e["line"] for e in r["errors"]], [3, 5])

    def test_importing_the_same_file_twice_adds_nothing(self):
        text = "date,from,to,flight\n2024-03-09,ATL,LHR,DL30\n"
        self.h.import_csv(text)
        self.assertEqual(self.h.import_csv(text),
                         {"added": 0, "skipped": 1, "errors": []})

    def test_same_route_same_day_different_flight_number_is_kept(self):
        text = ("date,from,to,flight\n2024-03-09,ATL,JFK,DL1\n"
                "2024-03-09,ATL,JFK,DL2\n")
        self.assertEqual(self.h.import_csv(text)["added"], 2)

    def test_accepts_common_header_names_and_a_byte_order_mark(self):
        text = "﻿Date,Origin,Destination,Carrier\n2024-03-09,ATL,LHR,Delta\n"
        self.assertEqual(self.h.import_csv(text)["added"], 1)
        self.assertEqual(self.h.list()[0]["airline"], "Delta")

    def test_missing_required_column_names_what_is_missing(self):
        with self.assertRaises(ValueError) as cm:
            self.h.import_csv("date,from\n2024-03-09,ATL\n")
        self.assertIn("to", str(cm.exception))


class TestIsolation(HistoryCase):

    def setUp(self):
        super().setUp()
        self.other = self.store.for_user(self.users.create("Bob", "bob")["id"])

    def test_each_user_sees_only_their_own_flights_and_stats(self):
        self.h.add("2024-03-09", "ATL", "LHR")
        self.other.add("2024-05-01", "ATL", "JFK")
        self.assertEqual([f["to"]["iata"] for f in self.h.list()], ["LHR"])
        self.assertEqual([f["to"]["iata"] for f in self.other.list()], ["JFK"])
        self.assertEqual(self.h.stats()["flights"], 1)
        self.assertEqual(self.other.snapshot()["stats"]["airports"], 2)

    def test_another_users_flight_looks_exactly_like_a_missing_one(self):
        f = self.h.add("2024-03-09", "ATL", "LHR")
        self.assertIsNone(self.other.get(f["id"]))
        self.assertIsNone(self.other.update(f["id"], "2024-03-10", "ATL", "JFK"))
        self.assertFalse(self.other.delete(f["id"]))
        self.assertEqual(self.h.get(f["id"])["to"]["iata"], "LHR")

    def test_import_duplicates_are_judged_per_user(self):
        text = "date,from,to\n2024-03-09,ATL,LHR\n"
        self.h.import_csv(text)
        self.assertEqual(self.other.import_csv(text)["added"], 1)
        self.assertEqual(self.h.import_csv(text)["skipped"], 1)

    def test_deleting_a_user_removes_their_flights_only(self):
        self.h.add("2024-03-09", "ATL", "LHR")
        self.other.add("2024-05-01", "ATL", "JFK")
        self.users.delete(self.uid)
        self.assertEqual(self.h.list(), [])
        self.assertEqual(len(self.other.list()), 1)


class TestExport(HistoryCase):

    def test_export_starts_with_the_template_header(self):
        self.assertEqual(self.h.export_csv(), template_csv())

    def test_export_imports_back_to_the_same_flights(self):
        self.h.add("2024-03-09", "ATL", "LHR", airline="Delta",
                   flight_number="DL30", aircraft="A333", seat="34A",
                   notes='window, "left" side')
        self.h.add("2020-01-01", "ATL", "JFK")
        other = self.store.for_user(self.users.create("Bob", "bob")["id"])
        self.assertEqual(other.import_csv(self.h.export_csv()),
                         {"added": 2, "skipped": 0, "errors": []})
        strip = lambda fs: [{k: v for k, v in f.items() if k != "id"} for f in fs]
        self.assertEqual(strip(other.list()), strip(self.h.list()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
