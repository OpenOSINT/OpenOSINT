# OpenOSINT News Monitor — Real-Time Global News Search

Search worldwide news coverage by keyword and get back matching articles as they're published — powered by the free, keyless GDELT Project.

## What it does

Given a keyword query, it searches the [GDELT DOC 2.0 API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) — a real-time, worldwide monitor of online news coverage — and returns every matching article with its title, URL, publisher domain, language, source country, and when it was seen.

## Use cases

- **Brand & crisis monitoring** — see what's being published about your brand, product, or a crisis right now, worldwide
- **Geopolitical & security research** — track breaking coverage of a conflict, event, or entity across languages and countries
- **Market intelligence** — spot emerging coverage of a competitor, technology, or trend before it's aggregated elsewhere
- **Journalism & OSINT investigations** — find primary-source articles fast, filtered by recency

## Input

| Field | Type | Description |
|-------|------|-------------|
| `query` | string | Keywords to search for. Supports quoted phrases and OR groups. |
| `timespanMinutes` | integer | Lookback window in minutes (default 60, clamped to 15-1440). |

## Example input

```json
{
  "query": "ukraine",
  "timespanMinutes": 60
}
```

## Example output

```json
{
  "query": "ukraine",
  "title": "Real hardship and difficulties lie ahead in fight for Ukraine",
  "url": "https://example-news.com/article-1",
  "domain": "example-news.com",
  "language": "English",
  "sourceCountry": "United Kingdom",
  "seenDate": "20260913T091500Z",
  "timespanMinutes": 60,
  "checkedAt": "2026-09-17T12:00:00Z"
}
```

`sourceCountry` and `language` are `null` when GDELT couldn't determine one. GDELT's DOC 2.0 API doesn't expose a per-article tone/sentiment score in this mode, so no `tone` field is included — a value here would have to be fabricated, and this Actor never does that.

## Pricing

Pay per event:

- **`news-article`** — charged once per article returned.

Nothing is charged for an invalid query or a search that returns zero articles.

## Use with AI agents (MCP)

This Actor is available as an MCP tool via the [Apify MCP Server](https://apify.com/apify/actors-mcp-server) — add it to Claude, Cursor, or Windsurf and the agent can call it directly, no local install required.

## Data sources

- [GDELT Project](https://www.gdeltproject.org/) DOC 2.0 API — public, keyless, real-time worldwide news monitoring. No paid or resale-restricted API is used. This Actor respects GDELT's rate limits (at most one request every 5 seconds, with longer backoff on HTTP 429) and never calls the paid GDELT Cloud offering.

This Actor originally used GDELT's GEO 2.0 API (geolocated news mentions). That endpoint started returning HTTP 404 for every query — confirmed directly, including GDELT's own documented example URLs — while this DOC 2.0 endpoint kept working normally. No official GDELT deprecation notice was found for GEO 2.0 at the time of this change.

## Part of OpenOSINT

This Actor is part of the [OpenOSINT](https://openosint.tech) toolkit — an open-source (MIT) OSINT agent, MCP server, and CLI.

## Acceptable Use

For authorized security research, monitoring, and investigations only. Do not use this Actor for stalking, harassment, or doxxing. You are responsible for complying with applicable laws in your jurisdiction.
