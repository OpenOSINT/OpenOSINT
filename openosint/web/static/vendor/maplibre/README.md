# Vendored: MapLibre GL JS

This directory holds a **vendored, offline** copy of MapLibre GL JS. OpenOSINT is
an OSINT tool: it must run fully offline and must never announce its own
execution to a third party (a CDN request would). Nothing here is fetched at
runtime — the browser loads only these local files.

| Asset | Version | Source | License |
|---|---|---|---|
| `maplibre-gl.min.js` | 5.24.0 | https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/5.24.0/maplibre-gl.min.js | BSD-3-Clause (`LICENSE.txt`) |
| `maplibre-gl.min.css` | 5.24.0 | https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/5.24.0/maplibre-gl.min.css | BSD-3-Clause (`LICENSE.txt`) |

`5.24.0` (not `6.x`) is deliberate: at vendor time, `6.0.0` had not left prerelease
(cdnjs/npm only listed `6.0.0-0` .. `6.0.0-19`). `5.24.0` is the latest stable
release and already has everything this app needs — globe projection shipped in
`5.0.0` (Jan 2025). Bump to `6.x` once it tags a real stable release.

Globe projection tiles are never fetched by the browser directly — the map
style's raster source points at this app's own `GET /api/tiles/{z}/{x}/{y}`
route (see `openosint/web_server.py`), which fetches from EOX server-side,
caches, and streams the bytes back. The browser never talks to
`tiles.maps.eox.at` (or any CDN) directly.

## Updating

Re-download the exact pinned version's `maplibre-gl.min.js` and
`maplibre-gl.min.css` from cdnjs, refresh the version in the table above, and
re-extract `LICENSE.txt` from the matching tag of
https://github.com/maplibre/maplibre-gl-js. Do not edit the minified files by
hand.
