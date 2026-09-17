# Pricing — OpenOSINT News Monitor

Configure these events and prices in the Apify Console under **Publication > Monetization**. The values below are suggestions, not fixed.

| Event name | When it fires | Suggested price |
|---|---|---|
| `news-article` | Once per article returned for the query. | $0.003 |

## Design notes

- A broad query during a major news event can return up to 75 articles in one run (`_MAXRECORDS` in `src/main.py`, well under GDELT's own 250-record hard cap) — at the suggested price that's a ~$0.23 ceiling per run. Raise `_MAXRECORDS` or the price if you want more headroom.
- Nothing is charged for an invalid query or a zero-result search — only for articles actually found.
