# Vendored: Alpine.js

This directory holds a **vendored, offline** copy of Alpine.js. OpenOSINT is
an OSINT tool: it must run fully offline and must never announce its own
execution to a third party (a CDN request would). Nothing here is fetched at
runtime — the browser loads only these local files.

| Asset | Version | Source | License |
|---|---|---|---|
| `alpine.min.js` | 3.14.1 | https://cdn.jsdelivr.net/npm/alpinejs@3.14.1/dist/cdn.min.js | MIT (`LICENSE.md`) |

## Updating

Re-download the exact pinned version, refresh the version in the table, and
copy `LICENSE.md` from the matching tag of https://github.com/alpinejs/alpine.
Do not edit the minified file by hand.
