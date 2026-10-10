# OpenOSINT Cloud — Deploy Guide

Hosted REST and MCP API for IP and domain infrastructure intelligence.  One call, one bill, no infra to manage.  Hosted on Heroku.  Access is invite-only — contact commercial@openosint.tech; there is no self-serve checkout or billing processor wired up.

**Scope:** IP geolocation, ISP/ASN, proxy/VPN/datacenter/Tor detection, IP abuse reputation, DNS records, subdomain enumeration.  This service does **not** search for personal data about individuals and does not use leaked or breached data sources.

---

## 1. Prerequisites

- Heroku CLI installed and logged in (`heroku login`)
- This repo cloned locally

---

## 2. Heroku deploy

```bash
# Create app
heroku create your-app-name

# Add Postgres (free hobby tier is sufficient to start)
heroku addons:create heroku-postgresql:essential-0

# Set upstream keys used by the v1 tool set
heroku config:set IP2LOCATION_API_KEY=...
heroku config:set ABUSEIPDB_API_KEY=...
heroku config:set IPINFO_TOKEN=...          # optional, raises ipinfo rate limit

# Deploy
git push heroku main

# Initialise the database schema (run once)
heroku run psql \$DATABASE_URL -f db/init.sql

# Confirm the web dyno is up
heroku open
heroku logs --tail
```

The server binds to `$PORT` (set by Heroku automatically).

---

## 3. Provisioning a customer (manual — no self-serve checkout)

There is no automated purchase flow. To grant access:

1. Generate an API key and insert a row directly into the `customers` table (`api_key`, `credits`, `plan`) — e.g. via `heroku pg:psql`.
2. Email the customer their key.
3. The customer logs into `/dashboard` (GitHub/Google OAuth) and pastes the key into the "Already have a key?" form, which calls `POST /v1/link-key`.

Refills/renewals are manual too — there is no automatic credit top-up. Update the `credits` column directly when a customer pays.

---

## 4. Running locally

```bash
# Install with cloud extras
pip install -e ".[dev]"
pip install fastapi uvicorn[standard] asyncpg httpx pydantic

# Copy and fill in secrets (DATABASE_URL optional — omit for in-memory backend)
cp .env.example .env

# Start the gateway
uvicorn cloud.main:app --reload --port 8000
```

---

## 5. Running the test suite

```bash
pytest tests/test_cloud.py -v
```

No network calls are made.  The tests run against the in-memory backend.

---

## 6. MCP server endpoint

The gateway exposes a hosted MCP server at `/mcp` using the Streamable HTTP transport (MCP SDK ≥ 1.0.0).  Connect any MCP-compatible client — Claude Desktop, Claude Code, or a custom agent — directly to the hosted API without running any local server.

### Connection URL

```
https://your-app.herokuapp.com/mcp
```

### Authentication

Pass your OpenOSINT Cloud API key as an **`Authorization: Bearer`** header.  In `claude_desktop_config.json` or equivalent:

```json
{
  "mcpServers": {
    "openosint-cloud": {
      "url": "https://your-app.herokuapp.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

### Available MCP tools (5)

The same 5 infrastructure tools as `/v1/enrich`:

| MCP tool | What it returns | Key source |
|---|---|---|
| `search_ip` | Geolocation, ISP, ASN, hostname (ipinfo.io) | customer BYOK — `ipinfo` |
| `search_ip2location` | Proxy/VPN/Tor/datacenter, threat score (IP2Location.io) | server — included |
| `search_abuseipdb` | Abuse confidence score, reports, ISP (AbuseIPDB) | customer BYOK — `abuseipdb` |
| `search_dns` | A, AAAA, MX, NS, TXT, CNAME, SOA records | none |
| `search_domain` | Subdomain enumeration by scraping search engines and aggregators (noisy; disabled unless the operator enables active tools) | none |

Each tool takes one string parameter `target` (an IP address or domain name).  BYOK tools require the corresponding key to be stored first via `POST /v1/keys`; a missing key returns a structured error string, not a protocol error.

### Credit metering

1 credit is deducted on success — same rule as the REST endpoint.  Upstream errors (`Scan error:...`) are **not** charged.

### Listing on Smithery / Glama / mcp.so

Point the registry at `https://your-app.herokuapp.com/mcp`.  The server's capability advertisement (tool list, descriptions) is returned via the standard `initialize` → `tools/list` MCP exchange; no separate manifest URL is needed.

---

## 7. Syntax / import check

```bash
python -m py_compile cloud/main.py cloud/db.py cloud/tools.py \
  cloud/auth.py cloud/config.py \
  cloud/routes/enrich.py cloud/routes/usage.py
```

---

## 8. curl examples

### Check your balance

```bash
curl -s https://your-app.herokuapp.com/v1/usage \
  -H "X-API-Key: YOUR_API_KEY" | jq .
# → {"plan":"starter","credits":999}
```

### Run an OSINT tool

```bash
curl -s -X POST https://your-app.herokuapp.com/v1/enrich \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tool":"search_ip","target":"8.8.8.8"}' | jq .
```

```json
{
  "tool": "search_ip",
  "target": "8.8.8.8",
  "timestamp": "2026-06-12T10:00:00+00:00",
  "results": [
    "IP intelligence for '8.8.8.8':",
    "[+] Ip: 8.8.8.8",
    "[+] Hostname: dns.google",
    "[+] Org: AS15169 Google LLC",
    "[+] City: Mountain View",
    "[+] Country: US"
  ],
  "error": null,
  "credits_left": 998
}
```

Out of credits returns a 402 pointing at `commercial@openosint.tech` instead of a checkout URL.

---

## 9. Environment variable reference

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | Production | Heroku Postgres DSN (set by addon) |
| `IP2LOCATION_API_KEY` | Recommended | search_ip2location tool (sponsored) |
| `ABUSEIPDB_API_KEY` | Recommended | search_abuseipdb tool |
| `IPINFO_TOKEN` | Optional | Raises ipinfo.io rate limit |

---

## 10. v1 synchronous tool allow-list

IP and domain infrastructure intelligence only.

| Tool | What it returns | Upstream | Key source | Provider string | Typical latency |
|---|---|---|---|---|---|
| `search_ip` | Geolocation, ISP, ASN, hostname | ipinfo.io | **customer** (BYOK) | `ipinfo` | ~1 s |
| `search_ip2location` | Proxy/VPN/Tor/datacenter detection, threat score | IP2Location.io (sponsored) | server | — | ~1–2 s |
| `search_abuseipdb` | IP abuse reputation, report history | AbuseIPDB | **customer** (BYOK) | `abuseipdb` | ~1–2 s |
| `search_dns` | A, AAAA, MX, NS, TXT, CNAME, SOA records | dnspython | none | — | ~2–5 s |
| `search_domain` | Subdomain enumeration by scraping search engines and aggregators (noisy; disabled unless the operator enables active tools) | sublist3r | none | — | ~10–30 s |

**Key source legend:**
- **customer** — customer must add their own key via `POST /v1/keys` before calling this tool; missing key returns 422.
- **server** — key is provided by the operator; customers get it included at no extra step.
- **none** — no credential required.

Credits are **not** deducted when a tool returns an upstream error (`Scan error: ...`).

All tool calls are wrapped in a 25 s `asyncio.wait_for` (Heroku 30 s H12 limit - 5 s headroom).  A 504 is returned if the tool exceeds the budget.

---

## 11. BYOK key management

Customers store their own upstream API keys once; every `POST /v1/enrich` call resolves them automatically.  Keys are encrypted at rest with Fernet (`CONFIG_ENCRYPTION_KEY`).

### Add a key

```bash
# Add an ipinfo.io token
curl -s -X POST https://your-app.herokuapp.com/v1/keys \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"provider": "ipinfo", "secret": "your_ipinfo_token"}'
# -> HTTP 204 No Content

# Add an AbuseIPDB key
curl -s -X POST https://your-app.herokuapp.com/v1/keys \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"provider": "abuseipdb", "secret": "your_abuseipdb_key"}'

```

### List stored keys (masked)

```bash
curl -s https://your-app.herokuapp.com/v1/keys \
  -H "X-API-Key: YOUR_API_KEY" | jq .
# -> [{"provider":"ipinfo","masked":"****a1b2"},{"provider":"abuseipdb","masked":"****xy99"}]
```

### Remove a key

```bash
curl -s -X DELETE https://your-app.herokuapp.com/v1/keys/ipinfo \
  -H "X-API-Key: YOUR_API_KEY"
# -> HTTP 204 No Content
```

### End-to-end: store an ipinfo key then run search_ip

```bash
# 1. Store the key (once)
curl -s -X POST https://your-app.herokuapp.com/v1/keys \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"provider": "ipinfo", "secret": "your_ipinfo_token"}'

# 2. Run search_ip -- stored key is resolved automatically, no extra header needed
curl -s -X POST https://your-app.herokuapp.com/v1/enrich \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tool": "search_ip", "target": "8.8.8.8"}' | jq .
```

### Operator setup: CONFIG_ENCRYPTION_KEY

```bash
# Generate a Fernet key (do this once, store it safely)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Set it on Heroku before first deployment with DATABASE_URL
heroku config:set CONFIG_ENCRYPTION_KEY=<generated_key>
```

> **Warning:** Never rotate `CONFIG_ENCRYPTION_KEY` without first decrypting and
> re-encrypting all rows in `customer_keys`.  Rotating without migration makes all
> stored secrets unreadable.

---

## 12. Waitlist

A public, unauthenticated demand-validation signup for a future self-serve Cloud
tier (Free/Pro/Team).  No payment processing — signup only.  Frontend page:
`docs/cloud/waitlist/index.html`.  Backend: `cloud/routes/waitlist.py`.

> **Current status:** the live waitlist page posts directly to
> [Formspree](https://formspree.io/) (`FORMSPREE_ENDPOINT` in the page's
> `<script>`), not to this gateway.  The `POST /v1/waitlist` /
> `GET /v1/waitlist/stats` routes, the `waitlist` table, the migration below,
> and their tests all still exist and pass — they're just not wired to the
> live page right now.  Switching the page back to this endpoint is a
> one-line change to `FORMSPREE_ENDPOINT`'s replacement in the script.

### Endpoint

```
POST /v1/waitlist
Content-Type: application/json

{
  "email": "analyst@example.com",
  "role": "soc_analyst",
  "use_case": "Enriching alerts with IP reputation",
  "plan_interest": "pro",
  "consent": true,
  "source": "utm_source=twitter"
}
```

Always returns `200` with the same success message, including on a duplicate
email (never reveals whether the address was already on the list) and on a
tripped honeypot (the hidden `website` field — non-empty means the row is
dropped, not stored).  `400` on missing consent, `422` on an invalid email,
`429` on the per-IP burst limiter (`WAITLIST_RATE_WINDOW_SECS` /
`WAITLIST_RATE_MAX_CALLS`, default 5 calls / 60 s).  No IP address is ever
written to the `waitlist` table.

CORS on this route (and only this route's origin set) is restricted to
`https://openosint.tech` plus `localhost`/`127.0.0.1` for dev — see
`cloud/main.py`.

### Migration (existing databases)

New installs get the `waitlist` table for free from `db/init.sql`.  For an
already-deployed database, run the idempotent migration:

```bash
heroku pg:psql -a your-app-name < db/migrations/0001_add_waitlist.sql
```

### Stats (operator only)

```bash
curl -s https://your-app.herokuapp.com/v1/waitlist/stats \
  -H "X-Setup-Token: $OPENOSINT_SETUP_TOKEN" | jq .
# -> {"total": 42, "by_role": {...}, "by_plan_interest": {...}, "by_source": {...}}
```

Gated by the same `OPENOSINT_SETUP_TOKEN` mechanism used elsewhere for
operator-only access — unset by default, so this route stays closed until an
operator opts in.  It never returns individual email addresses.

### Exporting emails

There is no endpoint that lists emails by design.  Export directly with SQL:

```bash
heroku pg:psql -a your-app-name -c \
  "COPY (SELECT email, role, plan_interest, source, created_at FROM waitlist ORDER BY created_at) TO STDOUT WITH CSV HEADER" \
  > waitlist_export.csv
```
