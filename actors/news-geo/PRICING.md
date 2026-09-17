# Pricing — OpenOSINT News Geo

Configure these events and prices in the Apify Console under **Publication > Monetization**. The values below are suggestions, not fixed.

| Event name | When it fires | Suggested price |
|---|---|---|
| `geo-location-result` | Once per geolocated location returned for the query. | $0.005 |

## Design notes

- A broad query during a major news event can return up to 250 locations in one run (GDELT's `maxpoints` cap) — at the suggested price that's a ~$1.25 ceiling per run. Lower the price, or lower `_DEFAULT_MAXPOINTS` in `src/main.py`, if that ceiling is too high for your audience.
- Nothing is charged for an invalid query or a zero-result search — only for locations actually found.
