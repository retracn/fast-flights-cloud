# fast-flights-cloud

**A [fast-flights](https://github.com/AWeirdDev/flights) integration for when Google starts blocking you: the same `get_flights()` call and `Flights` objects, fetched by a hosted Google Flights API.**

fast-flights works well for occasional searches. At volume, or from a busy server, Google starts answering with bot-detection pages and results stop parsing. On 2.x the fallback fetcher also fails with `401 no token provided`. See issues [#70](https://github.com/AWeirdDev/flights/issues/70), [#101](https://github.com/AWeirdDev/flights/issues/101) and [#109](https://github.com/AWeirdDev/flights/issues/109). fast-flights 3 accepts plug-in data sources. `fast_flights_cloud.Cloud` is one that runs the search on a hosted Google Flights API with proxy rotation, and hands you fast-flights' own `ResultList` of `Flights`, so the rest of your code stays the same.

```python
# pip install fast-flights-cloud      (or: pip install git+https://github.com/retracn/fast-flights-cloud)
# export APIFY_TOKEN=your_apify_token
from fast_flights import FlightQuery, Passengers, create_query, get_flights
from fast_flights_cloud import Cloud

query = create_query(
    flights=[FlightQuery(date="2026-11-12", from_airport="LHR", to_airport="JFK")],
    seat="economy", trip="one-way", passengers=Passengers(adults=1), currency="USD",
)
flights = get_flights(query, integration=Cloud())   # the only change

for f in flights:
    print(f.price, f.airlines, f.flights[0].departure, f.flights[0].plane_type)
```

Tested on 6 October 2026 from a cloud server: 22 flights for LHR → JFK in 5.2 seconds, with the unit tests passing on fast-flights 3.1.0.

## What carries over

- **Query:** origin and destination airports, date, one-way or round-trip (prices are round-trip totals, as on Google Flights), seat class, number of adults, currency, `max_stops` (0 or 1), `max_price` and `airlines`. The last two are applied to the results.
- **Results:** `Flights(type, price, airlines, flights, carbon)` with `SingleFlight` legs (airports with names and codes, departure and arrival dates and times, duration in minutes, aircraft type) and carbon figures in grams, plus `metadata.airlines`.
- **Not supported yet:** children and infants, multi-city trips, plain-text queries, and the hour, duration and layover filters (they're ignored). `Cloud()` raises a clear error for the first three.

## Options and cost

`Cloud(token=None, *, country="us", max_flights=30, max_charge_usd=0.25, timeout=300)`. `token` defaults to `APIFY_TOKEN`, and `country` sets Google's point of sale, which can change prices.

Searches run the [Google Flights Scraper](https://apify.com/automationnation/google-flights-scraper) Actor on your Apify account at **$0.20 per 1,000 flights**, so a 30-flight search costs about $0.006. A [free Apify account](https://console.apify.com/sign-up) includes $5 of credit a month. Your token is in [Settings → API & Integrations](https://console.apify.com/settings/integrations).

## Notes

- fast-flights 3.1.0 imports `typing_extensions` without declaring it, so this package depends on it. A clean install works either way.
- Want the raw data instead (flight numbers, layovers, legroom, emissions versus typical, a Google Flights link)? Call the Actor directly, or use the [AutomationNation MCP server](https://github.com/retracn/automationnation-mcp) from an AI agent.

MIT licensed. Not affiliated with fast-flights or Google.
