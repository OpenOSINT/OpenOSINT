# OpenOSINT Username Recon — Cross-Platform Account Finder

Give it a username, get back every platform where that exact handle is registered — **$0.04 per username**, up to 20 usernames per run, no API keys to configure. NSFW sites excluded by default.

## ✨ What you get

- Hundreds of sites checked per username (social media, developer platforms, gaming, forums) via [sherlock](https://github.com/sherlock-project/sherlock)
- Every confirmed hit, with platform name and direct URL
- A control-scan pass that removes false-positive sites before you ever see the results
- Per-username coverage stats (`accountsFound`, `sitesSkipped`) so you know when a scan was partial

## 🏆 Why this Actor

Several sherlock-based username Actors on the Store charge the same $0.04/username. What they don't do:

- **A control scan runs first.** Every run scans one random, never-registered 12-character hex string before it touches your input. Any site that reports *that* string as "claimed" — a wildcard DNS entry, a parked domain, a wiki that generates a valid-looking page for any string — is a confirmed false positive and gets dropped from your results, on top of a static denylist of sites already known to do this. You see accounts a control scan couldn't also "find."
- **Partial coverage is never hidden.** A handful of unresponsive sites shouldn't sink a whole scan, but silently dropping them would make an incomplete result look exhaustive. The number of sites skipped per username is reported in the run status and in a `SUMMARY` key-value-store record, so you know when coverage was partial.
- **Pricing that doesn't punish popular usernames.** You pay per username scanned, not per hit — a username with 100+ matches costs the same as one with zero.

## 🎯 Use cases

- **Fraud & KYC checks** — verify whether an applicant's claimed username actually exists where they say it does
- **Vendor & contractor vetting** — confirm a claimed handle before trusting the account behind it
- **Brand protection** — find every platform an impersonator or unauthorized reseller is using your brand's handle on
- **MSP & account-takeover audits** — see how widely a compromised or departing employee's username is reused across platforms
- **AI agents** — a fixed per-username price an agent can budget against while it follows up on name variants

## 🚀 How to use it

1. Open the Actor on Apify and paste in one or more usernames (or call it via API/MCP — see below)
2. Run it — Apify gives every new account free monthly platform credit, enough to try this Actor without paying out of pocket
3. Read confirmed accounts from the dataset, and check the `SUMMARY` key-value record for per-username coverage

## 💰 Pricing

Pay per event — **`username-scanned`: $0.04 per username**, charged once per username that produces at least a partial result set (at least one site batch scanned successfully), regardless of how many accounts were found.

| Usernames | Cost |
|---|---|
| 1 username | $0.04 |
| One full run (20 usernames, the per-run max) | $0.80 |
| ~250 usernames | ~$10 |
| ~2,500 usernames | ~$100 |

**Not charged:** discovered accounts (pushed to the dataset, but billed per username, not per hit), a username that fails validation, or a username whose scan fails entirely. The Actor checks the remaining budget before starting each username, so a capped run stops cleanly rather than overspending mid-scan.

## 📥 Input

| Field | Type | Description |
|-------|------|-------------|
| `usernames` | array | One or more usernames to investigate (max 20 per run, duplicates removed). |

```json
{
  "usernames": ["johndoe", "octocat"]
}
```

## 📤 Output

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

## 🤖 Use with AI agents (MCP)

This Actor is available as a hosted MCP tool — no server to run, no config file beyond the URL below:

```json
{
  "mcpServers": {
    "openosint-username-recon": {
      "url": "https://mcp.apify.com?tools=complete_analogy/openosint-username-recon"
    }
  }
}
```

Example prompt: *"Check whether the username 'johndoe99' is registered anywhere, filtering out false positives from a control scan."*

Because pricing is per-username rather than per-hit, an agent can query several name variants in one call without cost swinging based on how common each handle turns out to be.

## 🔌 Integrations

- **Apify API** — call this Actor from any language via the [Apify API](https://docs.apify.com/api/v2) or client SDKs (Python, JS)
- **Scheduled runs** — re-check a brand or executive handle list on a recurring Apify schedule
- **Webhooks** — fire a webhook to Zapier, Make, or n8n when a run finishes, to route new impersonation hits into a ticket, sheet, or Slack alert
- **Google Sheets** — export runs directly to Sheets for a shareable footprint tracker

## ❓ FAQ

**Is this legal to run against a public username?** Yes — this checks whether a public profile page exists at each platform's normal, unauthenticated URL. No login, scraping behind auth, or bypass of access controls is involved.

**Does this expose anyone's private information?** No. It confirms whether a handle is *registered* on a platform and returns the public profile URL — it does not access profile content, private data, or anything behind a login wall.

**How is this different from other sherlock-based Actors?** Most charge the same per-username price but skip the control scan — the same 12-hex-string check that catches wildcard DNS entries and parked-domain "hits" before they reach your results. This one runs it on every scan, and reports partial coverage explicitly instead of presenting a partial result as complete.

**What if a username comes back with zero hits?** That's still a billable, real result — a clean "not found anywhere in this catalog" is useful information, not a failed run. Only a scan that fails entirely (every site batch errors out) goes uncharged.

**What if my run has issues?** Check the run log first — most failures are a malformed username in the input list. If something looks wrong with billing or output, open an issue on the [GitHub repo](https://github.com/OpenOSINT/OpenOSINT) or reach out via the Actor's Store page.

## 🧰 More OpenOSINT Actors

| Actor | Give it | Get back | Price |
|---|---|---|---|
| [OpenOSINT Email Recon](https://apify.com/complete_analogy/openosint-email-recon?utm_source=apify&utm_medium=actor-readme&utm_campaign=username-recon-crosssell) | an email address | linked accounts across 100+ services | from $0.015/run |
| [OpenOSINT Domain Recon](https://apify.com/complete_analogy/openosint-domain-recon?utm_source=apify&utm_medium=actor-readme&utm_campaign=username-recon-crosssell) | a domain | A-F email-security grade, RDAP data, dork URLs | $0.02/domain |

Chain them in one investigation: a username hit on a developer platform often links a public email in its profile — feed that email into Email Recon, or the domain in its bio into Domain Recon.

## Data sources

- [sherlock](https://github.com/sherlock-project/sherlock) (MIT licensed) — the only third-party data source this Actor uses. No paid or resale-restricted APIs are involved.

## Part of OpenOSINT

This Actor is part of the [OpenOSINT](https://openosint.tech) toolkit — an open-source (MIT) OSINT agent, MCP server, and CLI.

## Acceptable Use

For authorized security research, checking your own accounts, and fraud prevention with a legitimate legal basis only. Do not use this Actor for stalking, harassment, or doxxing. You are responsible for complying with applicable laws and each platform's terms of service in your jurisdiction.

---

If this Actor was useful, a ⭐ review on the Store page helps other buyers find it.
