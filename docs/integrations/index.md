# Integrations

Per-vendor pages for OpenOSINT's sponsored tool integrations: what the
provider does, which tool(s) it plugs into, credential setup, and a
runnable example — verified against this codebase, not marketing copy.

## Disclaimer

Placement on this list is paid sponsorship under
[SPONSORSHIP.md](../../SPONSORSHIP.md). **Inclusion does not imply the
provider is technically superior to alternatives** — OpenOSINT doesn't
vouch for data quality or accuracy, sponsored or not. One vendor per
category holds the "Featured" slot at a time; that's a placement
exclusivity, not a merit ranking.

## By category

| Category | Status | Page |
|---|---|---|
| IP Geolocation & Threat Intelligence | Featured — IP2Location.io | [ip2location.md](ip2location.md) |
| Residential Proxies | Featured — RapidProxy | [rapidproxy.md](rapidproxy.md) |
| Breach / Compromised-Credential Data | **Open** | see [SPONSORSHIP.md](../../SPONSORSHIP.md) |
| Email / Identity Lookup | **Open** | see [SPONSORSHIP.md](../../SPONSORSHIP.md) |

Open categories have no sponsor yet — there's no placeholder integration to
document. Interested vendors should start at
[SPONSORSHIP.md](../../SPONSORSHIP.md).

## Adding a new page

Copy [`TEMPLATE.md`](TEMPLATE.md), fill in every section against the actual
tool code (not the vendor's marketing site), and add a row to the table
above. Every code example must run as-is against this repo; mark anything
unverifiable as `TODO` rather than guessing.
