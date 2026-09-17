# OpenOSINT Domain Recon — Email Security & Attack Surface Check

Give it a domain, get back its DNS footprint, an A-F email-security grade, RDAP registration data, and ready-to-use dork URLs — built for security teams vetting vendors, partners, or their own infrastructure.

## What it does

For each domain you provide, it:

- Enumerates DNS records (A, AAAA, MX, NS, TXT, CNAME, SOA) via [dnspython](https://www.dnspython.org/), and flags a nonexistent domain via `domainExists`
- Analyzes SPF, DMARC, and DKIM (common selectors, with wildcard-DNS and revoked-key detection so a domain that answers every possible selector isn't misreported) and grades the domain's email-spoofing resistance A-F
- Looks up RDAP registration data (registrar, creation/expiry dates, name servers, status codes only — no registrant contact data is ever read)
- Generates a set of Google dork URLs for further manual investigation

## Use cases

- **Security & vendor due diligence** — check a third party's email-spoofing exposure before trusting their domain in your supply chain
- **Fraud prevention** — a newly registered domain with no SPF/DMARC is a common phishing-infrastructure signature
- **Brand protection** — monitor lookalike domains for how exposed they are to spoofing
- **Attack surface mapping** — DNS + RDAP + dorks in one call for recon workflows

## Input

| Field | Type | Description |
|-------|------|-------------|
| `domains` | array | One or more domains to investigate (max 50 per run, duplicates removed). |

## Example input

```json
{
  "domains": ["example.com"]
}
```

## Example output

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

A domain that doesn't exist gets `"domainExists": false` and empty DNS/RDAP fields — still reported, but see Pricing below.

## Email security grading rubric

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

## Pricing

Pay per event:

- **`domain-report`** — charged once per domain that produces a report, **except** a confirmed-nonexistent domain (`domainExists: false`) — that's reported but not charged. Nothing is charged for malformed input or a domain whose lookups fail on every retry attempt.

## Use with AI agents (MCP)

This Actor is available as an MCP tool via the [Apify MCP Server](https://apify.com/apify/actors-mcp-server) — add it to Claude, Cursor, or Windsurf and the agent can call it directly, no local install required.

## Data sources

- [dnspython](https://www.dnspython.org/) (ISC licensed) for DNS resolution
- RDAP (RFC 7482/9083), bootstrapped via IANA's public registry — the modern, structured-JSON replacement for WHOIS, and the reason no registrant contact data ever appears in this Actor's output
- OpenOSINT's own dork-URL generator (no external API)

No paid or resale-restricted third-party APIs are used.

## Part of OpenOSINT

This Actor is part of the [OpenOSINT](https://openosint.tech) toolkit — an open-source (MIT) OSINT agent, MCP server, and CLI.

## Acceptable Use

For authorized security research, vetting your own domains or vendors, and fraud prevention with a legitimate legal basis only. Do not use this Actor for stalking, harassment, or doxxing. You are responsible for complying with applicable laws in your jurisdiction.
