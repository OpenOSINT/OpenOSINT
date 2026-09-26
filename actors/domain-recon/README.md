# OpenOSINT Domain Recon — Email Security & Attack Surface Check

Give it a domain, get back an A-F email-spoofing grade, its full DNS footprint, RDAP registration data, and ready-to-use dork URLs — **$0.02 per domain**, up to 50 domains per run, no API keys to configure. Nonexistent domains are reported but never charged.

## ✨ What you get

- DNS records: A, AAAA, MX, NS, TXT, CNAME, SOA (via [dnspython](https://www.dnspython.org/))
- SPF, DMARC, and DKIM analysis, rolled into a single **A-F email-security grade**
- RDAP registration data: registrar, creation/expiry dates, name servers, status codes
- A set of Google dork URLs for further manual investigation
- `domainExists` on every row, so a dead domain is a documented finding, not a silent gap

## 🏆 Why this Actor

Most domain-checker Actors on the Store stop at "here's the SPF record, figure out the rest yourself." This one grades it, and gets the grading right:

- **A published A–F rubric**, not a black-box score — see the full table below, so you can defend the grade to a client or auditor
- **`mailProfile`** — the fix for a real grading bug: a domain like `example.com` that explicitly declares it sends no mail (null MX + `SPF -all`) used to get capped at grade C for "missing DKIM." This Actor recognizes that pattern and grades non-mail domains on SPF + DMARC alone
- **RDAP, not WHOIS** — structured JSON, no registrant contact data ever read or returned
- **You don't pay for nothing** — a confirmed-nonexistent domain or a domain whose lookups fail on every retry is reported but not charged

## 🎯 Use cases

- **Fraud & KYC checks** — a newly registered domain with no SPF/DMARC is a common phishing-infrastructure signature
- **Vendor & third-party risk** — check a supplier's or partner's email-spoofing exposure before trusting their domain in your supply chain
- **Brand protection** — monitor lookalike domains for how exposed they are to being used in spoofed mail against your customers
- **MSP security audits** — batch-check every domain in a client's portfolio in one run, with a defensible grade per domain
- **AI agents** — a predictable per-domain price an agent can budget against before it starts pulling on threads

## 🚀 How to use it

1. Open the Actor on Apify and paste in one or more domains (or call it via API/MCP — see below)
2. Run it — Apify gives every new account free monthly platform credit, enough to try this Actor without paying out of pocket
3. Read the graded report in the dataset, or export it as JSON/CSV/Excel

## 💰 Pricing

Pay per event — **`domain-report`: $0.02 per domain**, charged once per domain that produces a report.

| Domains | Cost |
|---|---|
| 1 domain | $0.02 |
| One full run (50 domains, the per-run max) | $1.00 |
| ~500 domains | ~$10 |
| ~5,000 domains | ~$100 |

**Not charged:** a confirmed-nonexistent domain (`domainExists: false`), malformed input, or a domain whose lookups fail on every retry attempt.

## 📥 Input

| Field | Type | Description |
|-------|------|-------------|
| `domains` | array | One or more domains to investigate (max 50 per run, duplicates removed). |

```json
{
  "domains": ["example.com"]
}
```

## 📤 Output

```json
{
  "domain": "example.com",
  "domainExists": true,
  "dnsA": ["93.184.216.34"],
  "dnsMx": ["0 ."],
  "dnsNs": ["a.iana-servers.net", "b.iana-servers.net"],
  "dnsTxt": ["v=spf1 -all"],
  "spfRecord": "v=spf1 -all",
  "dmarcRecord": "v=DMARC1; p=reject",
  "dkimSelectorsFound": [],
  "dkimWildcard": false,
  "mailProfile": "no-mail",
  "emailSecurityGrade": "A",
  "emailSecurityIssues": [],
  "rdapRegistrar": "RESERVED-Internet Assigned Numbers Authority",
  "rdapCreatedDate": "1995-08-14T04:00:00Z",
  "rdapExpiresDate": "2027-08-13T04:00:00Z",
  "rdapNameServers": ["a.iana-servers.net", "b.iana-servers.net"],
  "rdapStatus": ["client delete prohibited", "client transfer prohibited", "client update prohibited"],
  "dorkUrls": [{"query": "\"example.com\" site:linkedin.com", "url": "https://www.google.com/search?q=..."}],
  "warnings": [],
  "checkedAt": "2026-09-17T12:00:00Z"
}
```

A domain that doesn't exist gets `"domainExists": false` and empty DNS/RDAP fields — still reported, but see Pricing above.

### Email security grading rubric

Grading starts at **A** and each issue below caps it at a ceiling — the worst ceiling that applies wins (rank A < B < C < D < F).

| Check | Condition | Caps at |
|---|---|---|
| SPF | No SPF record at all | **F** |
| SPF | Present but weak (`+all` or `~all`) | **C** |
| SPF | Present and strict (`-all`) | no cap |
| DMARC | No DMARC record at all | **D** |
| DMARC | `p=none` (monitor only, no enforcement) | **C** |
| DMARC | `p=quarantine` (suspicious mail spammed, not rejected) | **B** |
| DMARC | `p=reject` (enforced) | no cap |
| DKIM | Domain's DNS answers ANY selector (wildcard — unverifiable) | **C** |
| DKIM | No DKIM record found at any common selector | **C** |
| DKIM | A real DKIM record found at ≥1 common selector | no cap |

**DKIM is skipped entirely for a confirmed non-mail domain** (`mailProfile: "no-mail"`) — see below — since a domain that can't send mail has nothing for DKIM to sign. A domain reaches grade **A** only when every check that applies to it passes with no cap.

### `mailProfile`

Every report includes a `mailProfile` field explaining how the grade was computed:

- **`"no-mail"`** — [RFC 7505](https://www.rfc-editor.org/rfc/rfc7505) null MX (`0 .`), or no MX record at all, *combined with* an SPF record that is `-all` with no mechanism (`a`, `mx`, `ip4`, `ip6`, `include`, `exists`, `ptr`) authorizing any sender. This is a domain that has explicitly declared it neither sends nor receives mail — `example.com` is the canonical case. DKIM is not required for these domains; they're graded on SPF + DMARC alone.
- **`"sending"`** — the domain has a real (non-null) MX record, so it's set up to receive mail. DKIM absence still caps the grade.
- **`"unknown"`** — neither signal is conclusive (e.g. no MX record, but SPF isn't a bare `-all` either). Graded as if mail could flow — DKIM absence still caps the grade.

This distinction fixes a real grading bug: before it existed, a correctly locked-down non-mail domain like `example.com` (null MX, `SPF -all`, `DMARC p=reject`) was capped at grade C for "missing DKIM" — even though a domain that can't send mail has no use for DKIM in the first place.

## 🤖 Use with AI agents (MCP)

This Actor is available as a hosted MCP tool — no server to run, no config file beyond the URL below:

```json
{
  "mcpServers": {
    "openosint-domain-recon": {
      "url": "https://mcp.apify.com?tools=complete_analogy/openosint-domain-recon"
    }
  }
}
```

Example prompt: *"Check example.com's email-spoofing grade and RDAP registration data before I approve it as a vendor domain."*

## 🔌 Integrations

- **Apify API** — call this Actor from any language via the [Apify API](https://docs.apify.com/api/v2) or client SDKs (Python, JS)
- **Scheduled runs** — set up a recurring Apify schedule to re-check a vendor or brand-monitoring domain list on a cadence
- **Webhooks** — fire a webhook to Zapier, Make, or n8n when a run finishes, to pipe graded results straight into a ticket, sheet, or Slack alert
- **Google Sheets** — export runs directly to Sheets for a shareable vendor-risk tracker

## ❓ FAQ

**Is this legal to run against any domain?** Yes — everything here is public DNS and RDAP data, the same information any resolver or `whois`-equivalent client can fetch. No login, scraping, or bypass of access controls is involved.

**Does this expose the domain owner's personal information?** No. RDAP status codes, registrar, and dates are returned — registrant name, email, and address fields are never read or returned, even when the registry exposes them.

**How is this different from a free SPF/DMARC checker?** Most free checkers return raw records and leave the interpretation to you. This one applies a documented rubric, distinguishes non-mail domains so they aren't unfairly penalized for missing DKIM, and batches up to 50 domains per run with structured JSON/CSV/Excel export.

**What if a domain returns no results?** A domain that doesn't resolve at all comes back with `domainExists: false` and isn't charged — you still see it in the dataset as "checked, doesn't exist."

**What if my run has issues?** Check the run log first — most failures are a malformed domain in the input list. If something looks wrong with billing or output, open an issue on the [GitHub repo](https://github.com/OpenOSINT/OpenOSINT) or reach out via the Actor's Store page.

## 🧰 More OpenOSINT Actors

| Actor | Give it | Get back | Price |
|---|---|---|---|
| [OpenOSINT Email Recon](https://apify.com/complete_analogy/openosint-email-recon?utm_source=apify&utm_medium=actor-readme&utm_campaign=domain-recon-crosssell) | an email address | linked accounts across 100+ services | from $0.015/run |
| [OpenOSINT Username Recon](https://apify.com/complete_analogy/openosint-username-recon?utm_source=apify&utm_medium=actor-readme&utm_campaign=domain-recon-crosssell) | a username | every platform where it's registered, false positives filtered out | $0.04/username |

Chain them in one investigation: pull a domain from a discovered email's provider, or check the usernames found in a WHOIS/RDAP registrant history against Username Recon.

## Data sources

- [dnspython](https://www.dnspython.org/) (ISC licensed) for DNS resolution
- RDAP (RFC 7482/9083), bootstrapped via IANA's public registry — the modern, structured-JSON replacement for WHOIS, and the reason no registrant contact data ever appears in this Actor's output
- OpenOSINT's own dork-URL generator (no external API)

No paid or resale-restricted third-party APIs are used.

## Part of OpenOSINT

This Actor is part of the [OpenOSINT](https://openosint.tech) toolkit — an open-source (MIT) OSINT agent, MCP server, and CLI.

## Acceptable Use

For authorized security research, vetting your own domains or vendors, and fraud prevention with a legitimate legal basis only. Do not use this Actor for stalking, harassment, or doxxing. You are responsible for complying with applicable laws in your jurisdiction.

---

If this Actor was useful, a ⭐ review on the Store page helps other buyers find it.
