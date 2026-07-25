<!--
  Template for a per-sponsor integration page.
  Copy this file to docs/integrations/<vendor-slug>.md and fill in every section.
  Keep the section headings identical across pages so the index stays scannable.
  Every code example must be runnable against this codebase as-is. If you can't
  verify a line against the actual source, mark it TODO instead of guessing.
-->

# <Vendor Name>

> **Sponsored placement.** <Vendor Name> pays for the "<Category>" slot under
> OpenOSINT's [sponsorship program](../../SPONSORSHIP.md). Inclusion here is
> paid placement, not a technical endorsement — see the
> [disclaimer](index.md#disclaimer).

## What it does

<1-3 sentences on what the provider's API/service does, in plain terms.>

## Which OpenOSINT tools it plugs into

<Either a specific `search_*` tool module (link to the file), or — if there's
no dedicated tool — say so explicitly and describe the actual mechanism (e.g.
a generic layer the vendor's product plugs into). Do not imply a dedicated
integration exists if it doesn't.>

## Credential setup

- Env var: `<VAR_NAME>`
- Get a key: <link>
- Where it's read: `<file path>`

## Working example

```bash
<copy-pasteable shell example, verified against cli.py / the tool module>
```

```
<real or representative sample output, sourced from the code or README, not invented>
```

## Rate limits & cost

<What's actually documented/knowable — free tier, paid tiers, rate limit
behavior the tool handles (e.g. HTTP 429). Mark TODO if not verifiable from
this codebase or the vendor's own docs.>

## Link out

<Vendor sign-up / pricing link, with UTM tags matching the existing
convention: `?utm_source=openosint&utm_medium=integration_docs&utm_campaign=<vendor-slug>`>
