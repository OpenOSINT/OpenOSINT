# Pricing — OpenOSINT Username Recon

Configure these events and prices in the Apify Console under **Publication > Monetization**. The values below are suggestions, not fixed.

| Event name | When it fires | Suggested price |
|---|---|---|
| `username-found` | Once per (username, platform) pair where sherlock confirms the account exists. | $0.01 |

## Design notes

- Only one billable event exists for this Actor by design — a malformed username, an empty result, or a scan that ultimately fails after retries is never charged. This keeps the pricing model simple to reason about ("you only pay for what you find") at the cost of not recovering compute spent on usernames that come back empty.
- There is no flat per-run "start" fee (unlike some other OpenOSINT Actors) — that's a deliberate simplification for this Actor. Add one later (e.g. a `run-started` event) if empty-result runs turn out to be a meaningful cost sink.
