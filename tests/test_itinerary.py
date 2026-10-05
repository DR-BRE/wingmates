"""Pulling flights out of confirmation emails. Offline — synthetic fixtures.

The fixtures below are written for these tests, not copied from real mail, but
they follow the shapes airlines actually send: schema.org markup for Google,
microdata on older templates, and plain prose for everyone else.
"""
import unittest

from fc import itinerary
from fc.itinerary import HIGH, MEDIUM, Candidate, dedupe, extract


def jsonld(body: str) -> str:
    return f'<html><body><script type="application/ld+json">{body}</script></body></html>'


RESERVATION = jsonld("""
{"@context": "http://schema.org", "@type": "FlightReservation",
 "reservationNumber": "ABC123",
 "reservationFor": {"@type": "Flight", "flightNumber": "110",
   "airline": {"@type": "Airline", "iataCode": "AA", "name": "American Airlines"},
   "departureAirport": {"@type": "Airport", "iataCode": "SFO"},
   "departureTime": "2027-03-04T20:15:00-08:00",
   "arrivalAirport": {"@type": "Airport", "iataCode": "JFK"},
   "arrivalTime": "2027-03-05T06:30:00-05:00"}}
""")

RETURN_TRIP = jsonld("""
[{"@type": "FlightReservation", "reservationFor": {"@type": "Flight",
   "flightNumber": "BA112",
   "airline": {"@type": "Airline", "iataCode": "BA"},
   "departureAirport": {"@type": "Airport", "iataCode": "JFK"},
   "departureTime": "2027-05-01T18:30:00-04:00",
   "arrivalAirport": {"@type": "Airport", "iataCode": "LHR"}}},
 {"@type": "FlightReservation", "reservationFor": {"@type": "Flight",
   "flightNumber": "BA117",
   "airline": {"@type": "Airline", "iataCode": "BA"},
   "departureAirport": {"@type": "Airport", "iataCode": "LHR"},
   "departureTime": "2027-05-09T08:40:00+01:00",
   "arrivalAirport": {"@type": "Airport", "iataCode": "JFK"}}}]
""")

GRAPH = jsonld("""
{"@context": "https://schema.org", "@graph": [
  {"@type": "Organization", "name": "Example Air"},
  {"@type": "FlightReservation", "reservationFor": {"@type": "Flight",
    "flightNumber": "9",
    "airline": {"@type": "Airline", "iataCode": "NH"},
    "departureAirport": {"@type": "Airport", "iataCode": "NRT"},
    "departureTime": "2027-02-02T11:00:00+09:00",
    "arrivalAirport": {"@type": "Airport", "iataCode": "JFK"}}}]}
""")

MICRODATA = """
<div itemscope itemtype="http://schema.org/Flight">
  <meta itemprop="flightNumber" content="DL404">
  <meta itemprop="departureAirport" content="ATL">
  <meta itemprop="arrivalAirport" content="LHR">
  <meta itemprop="departureTime" content="2027-06-11T21:05:00-04:00">
</div>
"""

PROSE = """
Your trip is confirmed.
Flight UA 318 on 11 June 2027
ATL to JFK, departing 7:15am
"""

PROMO = """
Fares from $99! Our biggest sale of the year.
Explore destinations: ATL to JFK from $99, book now, offer ends soon.
2027-06-11
"""


class TestJsonLd(unittest.TestCase):

    def test_reads_a_single_reservation(self):
        found = extract(subject="Your trip", html=RESERVATION)
        self.assertEqual(len(found), 1)
        flight = found[0]
        self.assertEqual(
            (flight.date, flight.origin, flight.dest, flight.flight_number),
            ("2027-03-04", "SFO", "JFK", "AA110"))
        self.assertEqual(flight.confidence, HIGH)
        self.assertEqual(flight.method, "jsonld")
        self.assertEqual(flight.airline, "American Airlines")

    def test_reads_both_legs_of_a_return_trip(self):
        found = extract(subject="Your trip", html=RETURN_TRIP)
        self.assertEqual([(f.origin, f.dest) for f in found],
                         [("JFK", "LHR"), ("LHR", "JFK")])

    def test_reads_a_reservation_nested_in_a_graph(self):
        found = extract(subject="Booking confirmation", html=GRAPH)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].origin, found[0].dest), ("NRT", "JFK"))

    def test_keeps_the_local_departure_date(self):
        """A 23:50 departure must not slide a day because its UTC offset pushes
        it past midnight. This is the classic flight-software date bug."""
        html = jsonld("""
        {"@type": "FlightReservation", "reservationFor": {"@type": "Flight",
          "departureAirport": {"@type": "Airport", "iataCode": "SFO"},
          "departureTime": "2027-03-04T23:50:00-08:00",
          "arrivalAirport": {"@type": "Airport", "iataCode": "JFK"}}}""")
        self.assertEqual(extract(html=html)[0].date, "2027-03-04")

    def test_prefixes_a_bare_flight_number_with_the_airline_code(self):
        self.assertEqual(extract(html=RESERVATION)[0].flight_number, "AA110")

    def test_leaves_an_already_prefixed_number_alone(self):
        found = extract(html=RETURN_TRIP)
        self.assertEqual(found[0].flight_number, "BA112")

    def test_malformed_json_is_skipped_not_raised(self):
        self.assertEqual(extract(html=jsonld("{not json at all")), [])

    def test_a_leg_to_itself_is_rejected_as_a_parse_error(self):
        html = jsonld("""
        {"@type": "FlightReservation", "reservationFor": {"@type": "Flight",
          "departureAirport": {"@type": "Airport", "iataCode": "JFK"},
          "departureTime": "2027-03-04T10:00:00-05:00",
          "arrivalAirport": {"@type": "Airport", "iataCode": "JFK"}}}""")
        self.assertEqual(extract(html=html), [])


class TestMicrodata(unittest.TestCase):

    def test_reads_itemprop_attributes(self):
        found = extract(subject="E-ticket", html=MICRODATA)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].date, found[0].origin, found[0].dest),
                         ("2027-06-11", "ATL", "LHR"))
        self.assertEqual(found[0].confidence, HIGH)

    def test_html_without_flight_markup_yields_nothing(self):
        self.assertEqual(
            itinerary.from_microdata("<div itemtype='http://schema.org/Person'>"), [])


class TestText(unittest.TestCase):

    def test_reads_a_route_and_an_unambiguous_date(self):
        found = extract(subject="Your trip", text=PROSE)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].origin, found[0].dest, found[0].date),
                         ("ATL", "JFK", "2027-06-11"))

    def test_text_findings_are_only_ever_medium_confidence(self):
        self.assertEqual(extract(text=PROSE)[0].confidence, MEDIUM)

    def test_an_ambiguous_numeric_date_is_refused(self):
        """03/04/2027 is two different days depending on locale. Guessing is
        how flights get quietly filed on the wrong date."""
        self.assertEqual(extract(text="ATL to JFK on 03/04/2027"), [])

    def test_a_route_without_any_date_is_refused(self):
        self.assertEqual(extract(text="ATL to JFK, see you there"), [])

    def test_structured_markup_suppresses_the_text_fallback(self):
        """When JSON-LD already answered, regex must not add a second,
        worse-quality guess for the same email."""
        combined = RESERVATION + "<p>Also SFO to LHR on 2027-03-04</p>"
        found = extract(subject="Your trip", html=combined)
        self.assertTrue(all(f.method == "jsonld" for f in found))


class TestPromotionalFiltering(unittest.TestCase):

    def test_a_fare_sale_is_not_a_flight(self):
        self.assertEqual(extract(subject="Flight deals", text=PROMO), [])

    def test_a_real_confirmation_is_not_mistaken_for_marketing(self):
        self.assertTrue(extract(subject="Your trip", html=RESERVATION))


class TestDedupe(unittest.TestCase):

    def make(self, day, origin, dest, **kw):
        return Candidate(date=day, origin=origin, dest=dest, **kw)

    def test_collapses_confirmation_checkin_and_boarding_pass(self):
        same = [self.make("2027-03-04", "SFO", "JFK") for _ in range(3)]
        self.assertEqual(len(dedupe(same, [])), 1)

    def test_drops_flights_already_in_the_log(self):
        candidates = [self.make("2027-03-04", "SFO", "JFK"),
                      self.make("2027-03-09", "JFK", "SFO")]
        kept = dedupe(candidates, [("2027-03-04", "SFO", "JFK")])
        self.assertEqual([(c.origin, c.dest) for c in kept], [("JFK", "SFO")])

    def test_a_codeshare_number_does_not_make_a_second_flight(self):
        """The same leg arrives with the operating number in one email and a
        marketing number in another. One flight, not two."""
        pair = [self.make("2027-03-04", "SFO", "JFK", flight_number="AA110"),
                self.make("2027-03-04", "SFO", "JFK", flight_number="BA1510")]
        self.assertEqual(len(dedupe(pair, [])), 1)

    def test_results_are_ordered_by_date(self):
        out = dedupe([self.make("2027-05-01", "JFK", "LHR"),
                      self.make("2027-03-04", "SFO", "JFK")], [])
        self.assertEqual([c.date for c in out], ["2027-03-04", "2027-05-01"])


if __name__ == "__main__":
    unittest.main()
