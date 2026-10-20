# Pricing — OpenOSINT Username Recon

Configure these events and prices in the Apify Console under **Publication > Monetization**. The values below are suggestions, not fixed.

| Event name | When it fires | Suggested price |
|---|---|---|
| `username-scanned` | Once per username that produces at least a partial result set (at least one site chunk scanned successfully). | $0.04 |

## Design notes

- **Why per-username, not per-hit.** The Apify Store already has several sherlock-based username-recon Actors. Charging per (username, platform) hit — the original design — made cost unpredictable for buyers: a popular username like `octocat` matches ~112 sites, so at $0.01/hit that's $1.12 for one username, while comparable Store listings charge roughly $0.04 per username scanned regardless of hit count. Per-username pricing at $0.04 is competitive and predictable: the buyer knows the exact cost before running the Actor (`usernames.length * $0.04`, capped below by run limits).
- A username is charged once its scan produces **at least a partial result set** — i.e. at least one site chunk was successfully scanned, even if zero accounts were found (a clean "not registered anywhere" result is still a real finding worth paying for). A username whose scan fails entirely (every chunk errors out) is never charged.
- Discovered accounts are still pushed to the dataset — one item per (username, platform) hit — but that push is **not** a separate billable event. Only the per-username `username-scanned` event is charged.
- Before scanning each username, the Actor checks whether one more `username-scanned` event still fits within the run's configured charge limit and stops cleanly if it doesn't — so a capped budget never gets exceeded mid-scan.
- There is no flat per-run "start" fee (unlike some other OpenOSINT Actors) — that's a deliberate simplification for this Actor. Add one later (e.g. a `run-started` event) if that turns out to be a meaningful cost sink.
