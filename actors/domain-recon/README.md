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
  "dnsMx": [],
  "dnsNs": ["a.iana-servers.net", "b.iana-servers.net"],
  "dnsTxt": ["v=spf1 -all"],
  "spfRecord": "v=spf1 -all",
  "dmarcRecord": null,
  "dkimSelectorsFound": [],
  "dkimWildcard": false,
  "emailSecurityGrade": "D",
  "emailSecurityIssues": ["No DMARC policy — SPF/DKIM failures are not enforced."],
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
