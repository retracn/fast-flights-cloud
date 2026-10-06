import pytest
import requests
from fast_flights import FlightQuery, Passengers, create_query, get_flights
from fast_flights.exceptions import FlightsNotFound
from fast_flights.model import Flights

import fast_flights_cloud as ffc

ITEM = {
    "price": 504, "currency": "USD", "isBest": True, "airlines": ["JetBlue"], "mainAirlineCode": "B6", "flightNumbers": ["B6 2220"],
    "legs": [{"flightNumber": "B6 2220", "airline": "JetBlue", "from": "LHR", "fromAirport": "Heathrow Airport", "to": "JFK",
              "toAirport": "John F. Kennedy International Airport", "departure": "2026-11-12T07:25", "arrival": "2026-11-12T10:32",
              "durationMinutes": 487, "aircraft": "Airbus A321neo"}],
    "emissionsKg": 549, "typicalEmissionsKg": 343,
}
MULTI = {**ITEM, "price": 389, "airlines": ["Aer Lingus", "JetBlue"], "mainAirlineCode": "EI", "flightNumbers": ["EI 155", "B6 2220"]}


class FakeResp:
    def __init__(self, status, payload):
        self.status_code, self._payload, self.text = status, payload, str(payload)

    def json(self):
        return self._payload


@pytest.fixture
def posts(monkeypatch):
    log = []

    def fake_post(url, params=None, headers=None, json=None, timeout=None):
        log.append({"url": url, "params": params, "headers": headers, "json": json})
        return FakeResp(200, [ITEM, MULTI])

    monkeypatch.setattr(ffc.requests, "post", fake_post)
    return log


def query(**kw):
    flights = kw.pop("flights", [FlightQuery(date="2026-11-12", from_airport="LHR", to_airport="JFK")])
    return create_query(flights=flights, **{"seat": "economy", "trip": "one-way", "passengers": Passengers(adults=1), "currency": "USD", **kw})


def test_get_flights_returns_fast_flights_objects(posts):
    result = get_flights(query(), integration=ffc.Cloud(token="t"))
    assert len(result) == 2 and all(isinstance(f, Flights) for f in result)
    f = result[0]
    assert (f.type, f.price, f.airlines) == ("B6", 504, ["JetBlue"])
    leg = f.flights[0]
    assert (leg.from_airport.code, leg.to_airport.name, leg.departure.date, leg.departure.time, leg.duration, leg.plane_type) == (
        "LHR", "John F. Kennedy International Airport", (2026, 11, 12), (7, 25), 487, "Airbus A321neo")
    assert (f.carbon.emission, f.carbon.typical_on_route) == (549000, 343000)
    assert result[1].type == "multi"
    assert {a.code for a in result.metadata.airlines} == {"B6"}
    assert posts[0]["headers"]["Authorization"] == "Bearer t"


def test_query_maps_to_the_api_input(posts):
    q = query(flights=[FlightQuery(date="2026-11-12", from_airport="LHR", to_airport="JFK", max_stops=0),
                       FlightQuery(date="2026-11-19", from_airport="JFK", to_airport="LHR")],
              trip="round-trip", seat="premium-economy", passengers=Passengers(adults=2), currency="gbp")
    get_flights(q, integration=ffc.Cloud(token="t", country="gb"))
    assert posts[0]["json"] == {"origin": "LHR", "destination": "JFK", "adults": 2, "cabinClass": "premiumEconomy", "currency": "GBP",
                                "country": "gb", "maxFlightsPerSearch": 30, "departureDate": "2026-11-12", "returnDate": "2026-11-19", "stops": "nonstop"}


def test_client_side_filters(posts):
    assert [f.price for f in get_flights(query(max_price=400), integration=ffc.Cloud(token="t"))] == [389]
    only_ei = query(flights=[FlightQuery(date="2026-11-12", from_airport="LHR", to_airport="JFK", airlines=["EI"])])
    assert [f.price for f in get_flights(only_ei, integration=ffc.Cloud(token="t"))] == [389]


def test_unsupported_queries_and_errors(monkeypatch, posts):
    with pytest.raises(ValueError, match="Children"):
        get_flights(query(passengers=Passengers(adults=1, children=1)), integration=ffc.Cloud(token="t"))
    with pytest.raises(NotImplementedError):
        ffc.Cloud(token="t").fetch("Flights to JFK from LHR")
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    with pytest.raises(ValueError, match="APIFY_TOKEN"):
        ffc.Cloud()
    monkeypatch.setattr(ffc.requests, "post", lambda *a, **k: FakeResp(200, []))
    with pytest.raises(FlightsNotFound):
        get_flights(query(), integration=ffc.Cloud(token="t"))
    monkeypatch.setattr(ffc.requests, "post", lambda *a, **k: FakeResp(401, {"error": {"message": "User was not found"}}))
    with pytest.raises(requests.HTTPError, match="401 from the Google Flights API: User was not found"):
        get_flights(query(), integration=ffc.Cloud(token="bad"))
