# OpenOSINT Domain Recon — Email Security & Attack Surface Check

Give it a domain, get back its DNS footprint, an A-F email-security grade, WHOIS registration data, and ready-to-use dork URLs — built for security teams vetting vendors, partners, or their own infrastructure.

## What it does

For each domain you provide, it:

- Enumerates DNS records (A, AAAA, MX, NS, TXT, CNAME, SOA) via [dnspython](https://www.dnspython.org/)
- Analyzes SPF, DMARC, and DKIM (common selectors) and grades the domain's email-spoofing resistance A-F
- Looks up WHOIS registration data (registrar, creation/expiry dates, name servers only — registrant personal fields are intentionally dropped)
- Generates a set of Google dork URLs for further manual investigation

## Use cases

- **Security & vendor due diligence** — check a third party's email-spoofing exposure before trusting their domain in your supply chain
- **Fraud prevention** — a newly registered domain with no SPF/DMARC is a common phishing-infrastructure signature
- **Brand protection** — monitor lookalike domains for how exposed they are to spoofing
- **Attack surface mapping** — DNS + WHOIS + dorks in one call for recon workflows

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
  "dnsA": ["93.184.216.34"],
  "dnsMx": [],
  "dnsNs": ["a.iana-servers.net", "b.iana-servers.net"],
  "dnsTxt": ["v=spf1 -all"],
  "spfRecord": "v=spf1 -all",
  "dmarcRecord": null,
  "dkimSelectorsFound": [],
  "emailSecurityGrade": "D",
  "emailSecurityIssues": ["No DMARC policy — SPF/DKIM failures are not enforced."],
  "whoisRegistrar": "RESERVED-Internet Assigned Numbers Authority",
  "whoisCreatedDate": "1995-08-14T04:00:00",
  "whoisExpiresDate": "2026-08-13T04:00:00",
  "whoisNameServers": ["a.iana-servers.net", "b.iana-servers.net"],
  "dorkUrls": [{"query": "\"example.com\" site:linkedin.com", "url": "https://www.google.com/search?q=..."}],
  "warnings": [],
  "checkedAt": "2026-09-17T12:00:00Z"
}
```

## Pricing

Pay per event:

- **`domain-report`** — charged once per domain that produces a report (including a "domain doesn't resolve" finding — that's still useful signal). Nothing is charged for malformed input or a domain whose lookups fail on every retry attempt.

## Use with AI agents (MCP)

This Actor is available as an MCP tool via the [Apify MCP Server](https://apify.com/apify/actors-mcp-server) — add it to Claude, Cursor, or Windsurf and the agent can call it directly, no local install required.

## Data sources

- [dnspython](https://www.dnspython.org/) (ISC licensed) for DNS resolution
- [python-whois](https://pypi.org/project/python-whois/) for WHOIS lookups
- OpenOSINT's own dork-URL generator (no external API)

No paid or resale-restricted third-party APIs are used.

## Part of OpenOSINT

This Actor is part of the [OpenOSINT](https://openosint.tech) toolkit — an open-source (MIT) OSINT agent, MCP server, and CLI.

## Acceptable Use

For authorized security research, vetting your own domains or vendors, and fraud prevention with a legitimate legal basis only. Do not use this Actor for stalking, harassment, or doxxing. You are responsible for complying with applicable laws in your jurisdiction.
