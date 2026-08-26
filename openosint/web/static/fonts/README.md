# Self-hosted fonts

This directory holds **self-hosted, offline** copies of the UI fonts. OpenOSINT
is an OSINT tool: it must run fully offline and must never announce its own
execution to a third party. Loading fonts from Google Fonts transmits the
user's IP address to Google on every page load — these local files replace
that. Nothing here is fetched at runtime from any external host.

| Asset | Version | Source | License |
|---|---|---|---|
| `inter-latin.woff2`, `inter-latin-ext.woff2` | Inter v20 (variable, wght 400–700) | https://fonts.gstatic.com/s/inter/v20/ | SIL OFL 1.1 (`LICENSE-Inter.txt`) |
| `jetbrains-mono-latin.woff2`, `jetbrains-mono-latin-ext.woff2` | JetBrains Mono v24 (variable, wght 400–500) | https://fonts.gstatic.com/s/jetbrainsmono/v24/ | SIL OFL 1.1 (`LICENSE-JetBrainsMono.txt`) |

Both fonts are licensed under the **SIL Open Font License 1.1**, which
explicitly permits redistribution: the OFL grants permission to "use, study,
copy, merge, embed, modify, redistribute, and sell modified and unmodified
copies of the Font Software" provided the license and copyright notices are
kept — they are, in the two `LICENSE-*.txt` files here.

## Subsets

Only the `latin` and `latin-ext` subsets are vendored (`unicode-range` in
`fonts.css` scopes each file). Other scripts (Cyrillic, Greek, Vietnamese)
fall back to the system font stack — no network request is ever made for them.

## Updating

Fetch the CSS from
`https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap`
with a woff2-capable User-Agent, download the latin/latin-ext files it
references, refresh the version numbers in the table above, and update the
`unicode-range` values in `fonts.css` if they changed.
