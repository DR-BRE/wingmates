"""Shared fixtures for store and web tests. Offline."""
import tempfile
from pathlib import Path

from fc.airports import Airports
from fc.history import History
from fc.users import Users

AIRPORTS_CSV = """iata,icao,name,city,country,lat,lon,size
ATL,KATL,Hartsfield Jackson Atlanta International Airport,Atlanta,US,33.6367,-84.4281,3
JFK,KJFK,John F. Kennedy International Airport,New York,US,40.6394,-73.7793,3
LHR,EGLL,London Heathrow Airport,London,GB,51.4707,-0.4599,3
NRT,RJAA,Narita International Airport,Narita,JP,35.7686,140.3887,3
"""


def stores(case):
    """A temp data directory with an airport table, a History and a Users,
    cleaned up when the test case finishes."""
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    d = Path(tmp.name)
    (d / "airports.csv").write_text(AIRPORTS_CSV)
    airports = Airports(d / "airports.csv")
    return d, airports, History(airports, d / "flights.db"), Users(d / "flights.db")
