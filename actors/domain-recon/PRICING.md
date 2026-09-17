# Pricing — OpenOSINT Domain Recon

Configure these events and prices in the Apify Console under **Publication > Monetization**. The values below are suggestions, not fixed.

| Event name | When it fires | Suggested price |
|---|---|---|
| `domain-report` | Once per domain that produces a report — including a "domain doesn't resolve" finding, since that's still a useful signal for a security check. | $0.02 |

## Design notes

- A domain report is charged even when the domain doesn't resolve or has no email-security records — the *absence* of SPF/DMARC/DKIM (or of the domain itself) is exactly the kind of finding this Actor sells. Only a domain whose lookups fail on every retry attempt (network/infrastructure failure, not a real finding) goes uncharged.
- WHOIS and DNS are billed together under a single event rather than separately, keeping the pricing model simple. Split them into two events later if a customer only wants one half cheaply.
