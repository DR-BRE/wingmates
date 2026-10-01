"""Shared fixtures for store and web tests. Offline."""
import tempfile
from pathlib import Path
from unittest import mock

from fc.airports import Airports
from fc.history import History
from fc.turso import Turso
from fc.users import Users
from tests.fake_turso import FakeTurso

AIRPORTS_CSV = """iata,icao,name,city,country,lat,lon,size
ATL,KATL,Hartsfield Jackson Atlanta International Airport,Atlanta,US,33.6367,-84.4281,3
JFK,KJFK,John F. Kennedy International Airport,New York,US,40.6394,-73.7793,3
LHR,EGLL,London Heathrow Airport,London,GB,51.4707,-0.4599,3
NRT,RJAA,Narita International Airport,Narita,JP,35.7686,140.3887,3
"""


def temp_dir(case) -> Path:
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    return Path(tmp.name)


def database(case, d: Path):
    """The database a test uses: a SQLite file, or, for a test class with
    `on_turso = True`, Turso through the stand-in server."""
    if not getattr(case, "on_turso", False):
        return d / "flights.db"
    case.fake = FakeTurso(d / "remote.db")
    patcher = mock.patch("fc.turso.send", case.fake.send)
    patcher.start()
    case.addCleanup(patcher.stop)
    return Turso("libsql://wm-test.turso.io", "test-token")


def stores(case):
    """A temp data directory with an airport table, a History and a Users,
    cleaned up when the test case finishes. Sets case.database."""
    d = temp_dir(case)
    (d / "airports.csv").write_text(AIRPORTS_CSV)
    airports = Airports(d / "airports.csv")
    case.database = database(case, d)
    return d, airports, History(airports, case.database), Users(case.database)
