---
title: "External exposure report"
label: "Exposure report"
seo_title: "OpenOSINT exposure report: grade a domain from outside"
description: "openosint exposure grades one domain A to F from outside: SPF, DMARC, DKIM, TLS, registration and security headers. No AI or key needed. Beta."
group: Reference
order: 8
---
`openosint exposure` checks one domain from the outside and gives it a grade from A to F. It is passive and point-in-time, needs no AI provider and no API key, and is in **beta**: checks, scoring and the report format may change between releases.

```bash
openosint exposure example.com
```

## What it checks

| Check name | Covers | Contacts |
|---|---|---|
| `email` | SPF, DMARC, DKIM and MX | DNS only |
| `registration` | Domain age, expiry and DNSSEC via RDAP | The registry, not the target |
| `tls` | Certificate and protocol | A TLS handshake with the target on port 443 (the domain and `www`) |
| `http_headers` | Security headers | One HTTPS GET to `https://DOMAIN/`; redirects are followed |

It does not scan ports, log in to anything or collect personal data. The grade is not a certification and not proof of NIS2 or any other compliance.

## Options

| Option | Effect |
|---|---|
| `--json` | Structured JSON output. |
| `--report PATH.html` | Also write a self-contained HTML report that prints cleanly to PDF. |
| `--lang {en,it}` | Report language, used with `--report`. Default `en`. |
| `--lookalikes` | Also look for registered typo, homoglyph and TLD-swap domains. DNS only; not part of the grade. |
| `--resolver IP` | Recursive resolver for lookups outside the domain's own nameservers. |
| `--checks NAMES` | Run only some checks, comma-separated. |
| `--public-only` | Refuse targets that resolve to non-public addresses and vet every redirect hop. For hosted use; ignores proxy settings. |

## Run only the passive checks

```bash
openosint exposure example.com --checks email,registration
```

`email` and `registration` never connect to the target. A selection is **not graded**: the output has no letter and no score, because a grade from some of the checks would read like a full result.

```text
Not graded: only some checks were selected (not run: tls, http_headers).

Checks:
  email         OK       [passive]
  registration  OK       [passive]

Findings:
  [LOW] DMARC has no aggregate report address (dmarc_no_rua)
      fix: Add rua=mailto:... so you receive reports on who sends mail as your domain.
  [INFO] Domain registered 31.2 years ago (domain_age)
      fix: No action needed; age is context only.
```

Every finding carries its evidence and a suggested fix. The HTML report footer shows its `report_version`.

## Hosted version

[OpenOSINT Monitor](https://app.openosint.tech/monitor?utm_source=openosint.tech&utm_medium=referral&utm_campaign=docs) runs checks like these on a schedule and emails you when something changes.
