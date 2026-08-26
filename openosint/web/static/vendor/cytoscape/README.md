# Vendored: Cytoscape.js

This directory holds a **vendored, offline** copy of Cytoscape.js. OpenOSINT is
an OSINT tool: it must run fully offline and must never announce its own
execution to a third party (a CDN request would). Nothing here is fetched at
runtime — the browser loads only these local files.

| Asset | Version | Source | License |
|---|---|---|---|
| `cytoscape.min.js` | 3.30.2 | https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.30.2/cytoscape.min.js | MIT (`LICENSE.txt`) |

## Layout

We use Cytoscape's **built-in** layouts (`cose`, `breadthfirst`, `concentric`).
The `cytoscape-fcose` plugin is intentionally **not** vendored: its distributed
file `require()`s `cose-base` (which requires `layout-base`), neither of which
is bundled, so loaded on its own it never registers and every caller falls back
to the built-in `cose` layout anyway. Vendoring one non-functional file plus two
transitive dependencies to reproduce the built-in behavior is not worth it. If a
better layout is ever needed, vendor `layout-base`, `cose-base`, and
`cytoscape-fcose` together here and record them in the table above.

## Updating

Re-download the exact pinned version, refresh the version in the table, and
re-extract the license header into `LICENSE.txt`. Do not edit the minified file
by hand.
