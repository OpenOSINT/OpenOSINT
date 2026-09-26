<!-- TOMMASO: paste this into the Apify Console's README/description editor for openosint-email-recon. Verify every field name and event name against the live Console/actor.json before publishing — this file was written from the pricing and stats you gave me, not from the actor's source (it isn't in this repo). -->

# OpenOSINT Email Recon — Cross-Platform Account Finder

Give it an email address, get back every online service it's registered on — **starts at $0.015 per run**, scales with what's actually found, no API keys to configure.

## ✨ What you get

- Accounts linked to the email across 100+ online services, checked via [holehe](https://github.com/megadose/holehe)
- Per-service signal: whether the account exists, and — where the service leaks it — a masked account-recovery email or phone number
- Designed not to alert the target service in the course of checking <!-- TOMMASO: confirm this is accurate; phrase publicly as "designed not to alert the account holder," never as an absolute guarantee, since behavior depends on each of 100+ third-party services -->

## 🏆 Why this Actor

- **376 users, 50 monthly active, 5.0★** on the Store — the most-used OpenOSINT Actor, not a fresh, unproven listing
- **Pay for what you find, not a flat scan fee.** A run that finds nothing linked to an email costs almost nothing; a run that surfaces several accounts and a recovery hit reflects the value it delivered
- **Part of a maintained open-source toolkit** — the same account-enumeration logic runs in the [OpenOSINT](https://openosint.tech) CLI and MCP server, so it isn't a closed one-off script

## 🎯 Use cases

- **Fraud & KYC checks** — verify how an applicant's claimed email is actually used online before approving an account
- **Vendor & contractor vetting** — confirm the digital footprint behind a business contact's email
- **Brand protection** — spot an impersonator's or reseller's email footprint across services
- **MSP security audits** — check which services a client's staff emails are registered on as part of an account-hygiene review
- **AI agents** — a low, predictable start cost lets an agent probe an email before deciding whether to invest in deeper follow-up

## 🚀 How to use it

1. Open the Actor on Apify and paste in an email address (or call it via API/MCP — see below)
2. Run it — Apify gives every new account free monthly platform credit, enough to try this Actor without paying out of pocket
3. Read confirmed accounts, plus any recovery-email or phone-number hits, from the dataset

## 💰 Pricing

Pay per event:

| Event | Price |
|---|---|
| Run start | $0.015 |
| Per account found | $0.03 |
| Per enriched hit (recovery email or phone recovered) | $0.05 |

**Worked example:** a run that finds 8 linked accounts, 1 of which leaks a recovery contact, costs:
`$0.015 + (8 × $0.03) + (1 × $0.05) = $0.305`

Nothing beyond the $0.015 start fee is charged if a run finds no linked accounts at all.

## 📥 Input

| Field | Type | Description |
|-------|------|-------------|
| `email` | string | The email address to investigate. |

```json
{
  "email": "target@example.com"
}
```

## 📤 Output

<!-- TOMMASO: verify these field names against the live Actor's dataset schema / a real run before publishing -->
```json
{
  "email": "target@example.com",
  "service": "Spotify",
  "exists": true,
  "emailRecovery": null,
  "phoneNumber": null,
  "checkedAt": "2026-09-17T12:00:00Z"
}
```

One row per service where the account is confirmed to exist. `emailRecovery` and `phoneNumber` are populated only when the service itself exposes a masked recovery contact during the check.

## 🤖 Use with AI agents (MCP)

This Actor is available as a hosted MCP tool — no server to run, no config file beyond the URL below:

```json
{
  "mcpServers": {
    "openosint-email-recon": {
      "url": "https://mcp.apify.com?tools=complete_analogy/openosint-email-recon"
    }
  }
}
```

Example prompt: *"Check which online services are linked to contact@example.com, and flag anything that leaks a recovery email or phone number."*

## 🔌 Integrations

- **Apify API** — call this Actor from any language via the [Apify API](https://docs.apify.com/api/v2) or client SDKs (Python, JS)
- **Scheduled runs** — re-check a monitored email address on a recurring Apify schedule
- **Webhooks** — fire a webhook to Zapier, Make, or n8n when a run finishes, to route new findings into a ticket, sheet, or Slack alert
- **Google Sheets** — export runs directly to Sheets for a shareable footprint tracker

## ❓ FAQ

**Is this legal to run against any email address?** Yes — this checks each service's own public "is this email registered / password reset" signal, the same probe that service exposes to any visitor. No login or bypass of access controls is involved.

**Does the target get notified?** The check is designed not to alert the account holder, since it uses each service's own public signup/reset-check flow rather than actually triggering a reset — but behavior ultimately depends on each of 100+ third-party services' own implementation, which OpenOSINT does not control. <!-- TOMMASO: verify this framing matches what holehe actually does and how confident you want to be here -->

**How is this different from a free email-checker tool?** Most free tools check a handful of major services. This one checks 100+, surfaces recovery-contact leaks where a service exposes them, and is priced so a run that finds nothing costs a few cents rather than a flat fee.

**What if a run finds nothing?** You're only charged the $0.015 start fee — a clean "not registered anywhere checked" result costs almost nothing.

**What if my run has issues?** Check the run log first. If something looks wrong with billing or output, open an issue on the [GitHub repo](https://github.com/OpenOSINT/OpenOSINT) or reach out via the Actor's Store page.

## 🧰 More OpenOSINT Actors

| Actor | Give it | Get back | Price |
|---|---|---|---|
| [OpenOSINT Username Recon](https://apify.com/complete_analogy/openosint-username-recon?utm_source=apify&utm_medium=actor-readme&utm_campaign=email-recon-crosssell) | a username | every platform where it's registered, false positives filtered out | $0.04/username |
| [OpenOSINT Domain Recon](https://apify.com/complete_analogy/openosint-domain-recon?utm_source=apify&utm_medium=actor-readme&utm_campaign=email-recon-crosssell) | a domain | A-F email-security grade, RDAP data, dork URLs | $0.02/domain |

Chain them in one investigation: check the domain behind a discovered email's provider with Domain Recon, or a username variant of the same handle with Username Recon.

## Data sources

- [holehe](https://github.com/megadose/holehe) (MIT licensed) — the only third-party data source this Actor uses. No paid or resale-restricted APIs are involved.

## Part of OpenOSINT

This Actor is part of the [OpenOSINT](https://openosint.tech) toolkit — an open-source (MIT) OSINT agent, MCP server, and CLI.

## Acceptable Use

For authorized security research, checking your own accounts, and fraud prevention with a legitimate legal basis only. Do not use this Actor for stalking, harassment, or doxxing. You are responsible for complying with applicable laws and each platform's terms of service in your jurisdiction.

---

If this Actor was useful, a ⭐ review on the Store page helps other buyers find it.
