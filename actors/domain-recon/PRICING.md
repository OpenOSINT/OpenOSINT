# Pricing — OpenOSINT Domain Recon

Configure these events and prices in the Apify Console under **Publication > Monetization**. The values below are suggestions, not fixed.

| Event name | When it fires | Suggested price |
|---|---|---|
| `domain-report` | Once per domain that produces a report and is not confirmed nonexistent (`domainExists: false`). | $0.02 |

## Design notes

- A domain report is charged even when it has no email-security records (missing SPF/DMARC/DKIM) — that absence is exactly the kind of finding this Actor sells.
- A **confirmed-nonexistent domain** (DNS says NXDOMAIN with no NS/SOA, or RDAP returns 404) is still pushed to the dataset — the customer sees it checked out clean — but is **not charged**, since there's no registration/security posture to report on.
- A domain whose lookups fail on every retry attempt (network/infrastructure failure, not a real finding either way) also goes uncharged.
- RDAP and DNS are billed together under a single event rather than separately, keeping the pricing model simple. Split them into two events later if a customer only wants one half cheaply.
