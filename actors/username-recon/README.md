# OpenOSINT Username Recon — Cross-Platform Account Finder

Give it a username, get back every platform where that exact handle is registered — built for fraud teams, brand protection, and AI agents.

## What it does

For each username you provide, it checks hundreds of sites (social media, developer platforms, gaming, forums) via [sherlock](https://github.com/sherlock-project/sherlock) and reports every platform where an account exists. NSFW sites are excluded by default.

### The false-positive filter

Some sites answer "claimed" for *any* username you throw at them — a wildcard DNS entry, a parked domain, or a wiki that generates a valid-looking "User:&lt;name&gt;" page for any string, even one that was never registered. Left unfiltered, those sites would show up as a "hit" on every single run, which is just noise dressed up as a finding.

Before scanning your usernames, each run first scans one random, 12-character hex string — a username that is, for all practical purposes, guaranteed to have never been registered anywhere. Any site that reports that random string as "claimed" is a false positive for this run and gets excluded from your results, on top of a small static denylist of sites already confirmed to do this. This means you only ever see accounts that a control scan couldn't also "find" for a string nobody has ever used.

### Partial coverage is always reported

A handful of unresponsive sites shouldn't sink an entire scan. Sites are checked in small batches, and a batch that times out is skipped rather than retried — but skipped sites mean that username's result set is incomplete. The number of sites skipped per username is included in the run's status message and in the `SUMMARY` key-value-store record (see Output below), so you always know when coverage was partial rather than exhaustive.

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

### Run summary (key-value store)

Alongside the dataset, each run writes a `SUMMARY` record to its key-value store: a map of `{username: {accountsFound, sitesSkipped, checkedAt}}` covering every username that was scanned. Check this if you need per-username coverage stats without scanning the whole dataset.

## Pricing

Pay per event:

- **`username-scanned`** — charged once per username that produces at least a partial result set (at least one site batch scanned successfully), regardless of how many accounts were found. Not charged if a username's scan fails entirely.

Discovered accounts are still pushed to the dataset one row per hit, but that's not billed separately — you pay per username, not per hit. Nothing is charged for a username that fails validation, and the Actor checks the remaining budget before starting each username so a capped run stops cleanly rather than overspending mid-scan.

## Use with AI agents (MCP)

This Actor is available as an MCP tool via the [Apify MCP Server](https://apify.com/apify/actors-mcp-server) — add it to Claude, Cursor, or Windsurf and the agent can call it directly, no local install required. Because pricing is per-username rather than per-hit, an agent can query several usernames in one call without the cost swinging wildly based on how common each handle turns out to be — useful when an agent is following up leads (e.g. checking variants of a name) and needs predictable per-step cost to reason about its own budget.

## Data sources

- [sherlock](https://github.com/sherlock-project/sherlock) (MIT licensed) — the only third-party data source this Actor uses. No paid or resale-restricted APIs are involved.

## Part of OpenOSINT

This Actor is part of the [OpenOSINT](https://openosint.tech) toolkit — an open-source (MIT) OSINT agent, MCP server, and CLI.

## Acceptable Use

For authorized security research, checking your own accounts, and fraud prevention with a legitimate legal basis only. Do not use this Actor for stalking, harassment, or doxxing. You are responsible for complying with applicable laws and each platform's terms of service in your jurisdiction.
