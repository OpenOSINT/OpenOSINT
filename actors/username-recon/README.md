# OpenOSINT Username Recon — Cross-Platform Account Finder

Give it a username, get back every platform where that exact handle is registered — built for fraud teams, brand protection, and AI agents.

## What it does

For each username you provide, it checks hundreds of sites (social media, developer platforms, gaming, forums) via [sherlock](https://github.com/sherlock-project/sherlock) and reports every platform where an account exists. NSFW sites are excluded by default.

## Use cases

- **Brand monitoring** — find every platform an impersonator or unauthorized reseller is using your brand's handle on
- **Fraud & identity verification** — check whether an applicant's claimed username actually exists where they say it does
- **Account takeover exposure checks** — see how widely a compromised username is reused across platforms
- **Investigations & due diligence** — map an individual's or organization's public digital footprint

## Input

| Field | Type | Description |
|-------|------|-------------|
| `usernames` | array | One or more usernames to investigate (max 20 per run, duplicates removed). |

## Example input

```json
{
  "usernames": ["johndoe", "octocat"]
}
```

## Example output

```json
{
  "username": "octocat",
  "platform": "GitHub",
  "url": "https://github.com/octocat",
  "category": null,
  "checkedAt": "2026-09-17T12:00:00Z"
}
```

`category` is currently always `null` — sherlock's site catalog doesn't carry a per-platform category taxonomy.

## Pricing

Pay per event:

- **`username-found`** — charged once per (username, platform) hit that's actually found.

You never pay for a platform that comes back empty, and nothing is charged if a username fails validation or the scan itself errors out.

## Use with AI agents (MCP)

This Actor is available as an MCP tool via the [Apify MCP Server](https://apify.com/apify/actors-mcp-server) — add it to Claude, Cursor, or Windsurf and the agent can call it directly, no local install required.

## Data sources

- [sherlock](https://github.com/sherlock-project/sherlock) (MIT licensed) — the only third-party data source this Actor uses. No paid or resale-restricted APIs are involved.

## Part of OpenOSINT

This Actor is part of the [OpenOSINT](https://openosint.tech) toolkit — an open-source (MIT) OSINT agent, MCP server, and CLI.

## Acceptable Use

For authorized security research, checking your own accounts, and fraud prevention with a legitimate legal basis only. Do not use this Actor for stalking, harassment, or doxxing. You are responsible for complying with applicable laws and each platform's terms of service in your jurisdiction.
