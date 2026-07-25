# OpenOSINT — Sponsorship Prospectus

OpenOSINT is an open-source OSINT framework — an interactive AI REPL, a direct CLI, an MCP server, and a browser Web UI — wrapping intelligence tools that security researchers and OSINT practitioners configure with their own API keys. When a user sets up a new integration, the docs route them straight to that provider's sign-up page.

A **Featured Integration** sponsor is the recommended, default provider for one tool category — and no competitor gets that placement while you hold it.

## Who you reach

| Metric | Value | Source |
|--------|-------|--------|
| GitHub stars | ![GitHub stars](https://img.shields.io/github/stars/OpenOSINT/OpenOSINT?style=flat-square) | live |
| GitHub forks | ![GitHub forks](https://img.shields.io/github/forks/OpenOSINT/OpenOSINT?style=flat-square) | live |
| PyPI downloads / month | ![PyPI downloads](https://img.shields.io/pypi/dm/openosint?style=flat-square&label=PyPI%20downloads) | live |
| GitHub repo views (14-day, GitHub's max window) | 4,958 total / 2,375 unique | [`data/metrics/2026-07-25.json`](data/metrics/2026-07-25.json) |
| GitHub repo clones (14-day) | 831 total / 529 unique | [`data/metrics/2026-07-25.json`](data/metrics/2026-07-25.json) |
| MCP Registry | Published — `io.github.OpenOSINT/openosint` | — |

We don't run site analytics, so there's no "website visits" figure — GitHub's own traffic numbers above are the real proxy. Snapshot dated 2026-07-25; a fresh one lands weekly at [`data/metrics/`](data/metrics/) via [`scripts/sponsor_metrics.py`](scripts/sponsor_metrics.py).

Who's behind those numbers: security researchers and pentesters evaluating IP intelligence, breach data, and proxy-detection APIs; OSINT practitioners building investigation workflows; developers wiring intelligence tools into automated pipelines and AI agents; red teams and SOC analysts running the MCP server against Claude or Ollama. They arrive **motivated** — already running an OSINT framework, actively choosing a data provider — not general blog traffic.

## Tier

**Featured Integration** — the only tier. One vendor per category, full placement set either way you bill it.

| Billing | Price |
|---------|-------|
| Annual  | $2,000/year (≈ $167/month — 2 months free vs. monthly) |
| Monthly | $220/month |

Fiscal host: Open Collective / Open Source Collective — [opencollective.com/openosint_oss](https://opencollective.com/openosint_oss)

**What's included, recurring for as long as the sponsorship is active:**

- Recommended/default provider for one tool category (exclusive — see below)
- Logo + name + tagline in the README Featured Integrations block
- Sponsor badge in the README badge row
- "Featured (sponsored)" label, listed first in the Integrations table
- CLI startup banner on every `openosint` invocation
- Tool documentation page, sponsor-labeled, with a direct API-key sign-up link — see [docs/integrations/](docs/integrations/index.md) for the live examples (IP2Location.io, RapidProxy)
- Web UI settings panel — Featured integrations list
- `openosint sponsors` CLI subcommand output
- MCP Registry listing credit
- Card on the [media kit](https://openosint.tech/sponsors.html)
- Named in release notes when the integration ships or updates

**Referral funnel** — install → configure → click-through → activate:

1. User installs OpenOSINT (`pip install openosint` or from source).
2. User reads the Configuration table or tool docs — your API is listed as the recommended provider with a direct sign-up link.
3. User clicks through to your pricing or sign-up page.
4. User sets an API key; the integration runs live.

## Category exclusivity

This is the core mechanic: **one sponsor per category, full stop.** A taken category isn't contested while the sponsorship is active — no logo grid, no bidding a competitor onto the same page.

| Category | Status |
|----------|--------|
| Breach / Compromised-Credential Data | **OPEN** |
| Email / Identity Lookup | **OPEN** |
| IP Geolocation & Threat Intelligence | TAKEN — IP2Location.io |
| Residential Proxies | TAKEN — RapidProxy |

Your product doesn't map to a category above? Email us — new categories get created alongside a new live tool integration, not as a naming exercise.

## What we do not do

- No tracking scripts. No analytics pixel, no pageview beacon added on your behalf.
- No editorial control over tool selection. Sponsorship buys placement for one category; it doesn't buy a say in what other tools get added or how they're described.
- No endorsement of results. We don't vouch for your API's data quality or accuracy — users judge that themselves.

## How to start

1. Open Collective: [opencollective.com/openosint_oss](https://opencollective.com/openosint_oss) — self-serve monthly or annual.
2. Custom terms, multi-year contracts, or invoicing: email [commercial@openosint.tech](mailto:commercial@openosint.tech?subject=OpenOSINT%20Sponsorship%20Inquiry).
3. Once payment is confirmed we'll ask for a logo, tagline, sign-up URL, and API-key docs — placement typically ships within a few days.

Current sponsors: **[IP2Location.io](https://www.ip2location.io)** (IP Geolocation & Threat Intelligence) · **[RapidProxy](https://www.rapidproxy.io/?ref=openosint)** (Residential Proxies)

---

## For maintainers: adding or updating a sponsor

All sponsor data lives in [`sponsors.json`](sponsors.json) — a one-file change:

```json
{
  "name": "Acme Corp",
  "tagline": "Short description of what your product does",
  "url": "https://acme.example.com/?utm_source=openosint",
  "logo": "https://img.shields.io/badge/Acme-sponsored-blue?style=flat-square",
  "html_logo": "assets/acme-logo.svg",
  "tier": "featured",
  "tool": "search_acme",
  "category": "Your Category"
}
```

`logo` is the compact badge-style image used in README/badge contexts; `html_logo` (optional) overrides it with a real logo asset for the media-kit cards — omit it to reuse `logo` in both places.

Then regenerate README and the media kit from that single file:

```bash
python scripts/render_sponsors.py --docs-html docs/sponsors.html
```

CLI banner, Web UI, and `openosint sponsors` update automatically at runtime from the same file — nothing else to touch.

---

*OpenOSINT is for authorized security research only. See [DISCLAIMER.md](DISCLAIMER.md).*
