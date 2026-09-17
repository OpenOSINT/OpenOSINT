# OpenOSINT News Geo — Real-Time Geolocated News Search

Search worldwide news coverage by keyword and get back exactly where it's happening — powered by the free, keyless GDELT Project.

## What it does

Given a keyword query, it searches the [GDELT GEO 2.0 API](https://blog.gdeltproject.org/gdelt-geo-2-0-api-debuts/) — a real-time, worldwide monitor of online news coverage — and returns every geolocated point where matching coverage was found, with article counts and sample article URLs.

## Use cases

- **Brand & crisis monitoring** — see where in the world your brand, product, or a crisis is being covered right now
- **Geopolitical & security research** — track the geographic spread of coverage for a conflict, event, or entity
- **Market intelligence** — spot emerging regional coverage of a competitor, technology, or trend
- **Journalism & OSINT investigations** — find where a story is breaking geographically before it's aggregated elsewhere

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
  "locationName": "Kyiv, Kyiv Misto, Ukraine",
  "lat": 50.45,
  "lon": 30.52,
  "articleCount": 12,
  "sampleUrls": ["https://example-news.com/article-1"],
  "timespanMinutes": 60,
  "checkedAt": "2026-09-17T12:00:00Z"
}
```

## Pricing

Pay per event:

- **`geo-location-result`** — charged once per geolocated location returned.

Nothing is charged for an invalid query or a search that returns zero locations.

## Use with AI agents (MCP)

This Actor is available as an MCP tool via the [Apify MCP Server](https://apify.com/apify/actors-mcp-server) — add it to Claude, Cursor, or Windsurf and the agent can call it directly, no local install required.

## Data sources

- [GDELT Project](https://www.gdeltproject.org/) GEO 2.0 API — public, keyless, real-time worldwide news monitoring. No paid or resale-restricted API is used. This Actor respects GDELT's rate limits (at most one request every 5 seconds, with backoff on HTTP 429) and never calls the paid GDELT Cloud/BigQuery offering.

## Part of OpenOSINT

This Actor is part of the [OpenOSINT](https://openosint.tech) toolkit — an open-source (MIT) OSINT agent, MCP server, and CLI.

## Acceptable Use

For authorized security research, monitoring, and investigations only. Do not use this Actor for stalking, harassment, or doxxing. You are responsible for complying with applicable laws in your jurisdiction.
