"""Google Flights results for fast-flights that don't get blocked.

A fast-flights data-source integration: pass it to get_flights() and you get the same ResultList of Flights
objects, fetched by a hosted Google Flights API (an Apify Actor billed to your Apify account) instead of
your machine, so bot-detection pages, empty results and fetcher errors stop being your problem.

    from fast_flights import FlightQuery, Passengers, create_query, get_flights
    from fast_flights_cloud import Cloud

    query = create_query(flights=[FlightQuery(date="2026-11-12", from_airport="LHR", to_airport="JFK")],
                         seat="economy", trip="one-way", passengers=Passengers(adults=1), currency="USD")
    flights = get_flights(query, integration=Cloud())   # APIFY_TOKEN from the environment
"""
import os

import requests
from fast_flights.exceptions import FlightsNotFound
from fast_flights.integrations.base import DataSourceIntegration
from fast_flights.model import Airline, Airport, CarbonEmission, Flights, JsMetadata, SimpleDatetime, SingleFlight
from fast_flights.parser import ResultList
from fast_flights.pb.flights_pb2 import Passenger
from fast_flights.querying import Query

__all__ = ["Cloud"]
__version__ = "0.1.0"

ACTOR_URL = "https://api.apify.com/v2/acts/automationnation~google-flights-scraper/run-sync-get-dataset-items"
CABIN = {"economy": "economy", "premium-economy": "premiumEconomy", "business": "business", "first": "first"}


def _when(iso):
    """'2026-11-12T07:25' -> SimpleDatetime(date=(2026, 11, 12), time=(7, 25))."""
    date, _, time = (iso or "").partition("T")
    y, m, d = (int(x) for x in date.split("-")) if date else (0, 0, 0)
    hh, mm = (int(x) for x in time.split(":")[:2]) if time else (0, 0)
    return SimpleDatetime(date=(y, m, d), time=(hh, mm))


def _to_flights(item):
    legs = [
        SingleFlight(
            from_airport=Airport(name=leg.get("fromAirport") or "", code=leg.get("from") or ""),
            to_airport=Airport(name=leg.get("toAirport") or "", code=leg.get("to") or ""),
            departure=_when(leg.get("departure")),
            arrival=_when(leg.get("arrival")),
            duration=int(leg.get("durationMinutes") or 0),
            plane_type=leg.get("aircraft") or "",
        )
        for leg in item.get("legs") or []
    ]
    codes = {fn.split()[0] for fn in item.get("flightNumbers") or [] if fn}
    return Flights(
        type=item.get("mainAirlineCode") if len(codes) <= 1 else "multi",
        price=item.get("price"),
        airlines=list(item.get("airlines") or []),
        flights=legs,
        carbon=CarbonEmission(
            typical_on_route=int((item.get("typicalEmissionsKg") or 0) * 1000),
            emission=int((item.get("emissionsKg") or 0) * 1000),
        ),
    )


class Cloud(DataSourceIntegration[ResultList]):
    """fast-flights integration backed by a hosted Google Flights API.

    Args:
        token: Apify API token. Defaults to the APIFY_TOKEN environment variable. Get one free at
            https://console.apify.com/settings/integrations; flights cost $0.20 per 1,000 on your account.
        country: Two-letter Google country (point of sale), e.g. "us", "gb". Prices can differ by country.
        max_flights: Most flights to return per search (Google lists about 10-30).
        max_charge_usd: Spending cap per search.
        timeout: Seconds to wait for the search (usually a few seconds).
    """

    def __init__(self, token=None, *, country="us", max_flights=30, max_charge_usd=0.25, timeout=300):
        self.token = token or os.environ.get("APIFY_TOKEN")
        if not self.token:
            raise ValueError(
                "fast-flights-cloud needs an Apify API token: set APIFY_TOKEN or pass Cloud(token=...). "
                "Get one free at https://console.apify.com/settings/integrations."
            )
        self.country = country
        self.max_flights = max_flights
        self.max_charge_usd = max_charge_usd
        self.timeout = timeout

    def payload(self, q):
        """The Google Flights API input for a fast-flights Query."""
        if isinstance(q, str):
            raise NotImplementedError("fast-flights-cloud needs a Query from create_query(); plain-text queries aren't supported.")
        trip = q.get_trip_type()
        if trip == "multi-city":
            raise NotImplementedError("Multi-city trips aren't supported; search each leg as a one-way trip.")
        passengers = list(q.passengers)
        adults = passengers.count(Passenger.ADULT)
        if len(passengers) != adults:
            raise ValueError("Children and infants aren't supported yet; search with Passengers(adults=...) only.")
        outbound = q.flight_data[0]
        body = {
            "origin": outbound.from_airport.airport,
            "destination": outbound.to_airport.airport,
            "adults": max(1, adults),
            "cabinClass": CABIN.get(q.get_seat_type(), "economy"),
            "currency": (q.currency or "USD").upper(),
            "country": self.country,
            "maxFlightsPerSearch": self.max_flights,
        }
        if outbound.date:
            body["departureDate"] = outbound.date
        if trip == "round-trip" and len(q.flight_data) > 1 and q.flight_data[1].date:
            body["returnDate"] = q.flight_data[1].date
        if outbound.HasField("max_stops") and outbound.max_stops in (0, 1):
            body["stops"] = "nonstop" if outbound.max_stops == 0 else "oneStop"
        return body

    def fetch(self, q):
        body = self.payload(q)
        resp = requests.post(
            ACTOR_URL,
            params={"maxItems": self.max_flights, "maxTotalChargeUsd": f"{self.max_charge_usd:.2f}"},
            headers={"Authorization": f"Bearer {self.token}"},
            json=body,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            try:
                message = resp.json()["error"]["message"]
            except Exception:
                message = resp.text[:300]
            raise requests.HTTPError(f"{resp.status_code} from the Google Flights API: {message}", response=resp)
        items = resp.json()
        # Filters the API doesn't take, applied here so results match the query.
        if q.max_price:
            items = [i for i in items if i.get("price") is None or i["price"] <= q.max_price]
        wanted = set(q.flight_data[0].airlines)
        if wanted:
            items = [i for i in items if {fn.split()[0] for fn in i.get("flightNumbers") or [] if fn} & wanted]
        if not items:
            raise FlightsNotFound("no flights found")
        result = ResultList(_to_flights(i) for i in items)
        names = {}
        for i in items:
            for leg in i.get("legs") or []:
                code = (leg.get("flightNumber") or "").split(" ")[0]
                if code and leg.get("airline"):
                    names.setdefault(code, leg["airline"])
        result.metadata = JsMetadata(airlines=[Airline(code=c, name=n) for c, n in names.items()], alliances=[])
        return result
