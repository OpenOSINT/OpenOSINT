# Workflows and reading results

Commands below are CLI subcommands (`uvx --from openosint==2.38.0 openosint --json <cmd> <target>`). Names starting with `search_` are MCP tools, used only when the server is connected.

## Domain

1. `exposure DOMAIN` first: it gives the graded overview (email authentication, TLS, registration age/expiry/DNSSEC, security headers). Cite the check that produced each finding.
2. `dns DOMAIN` for raw records (A/AAAA/NS/MX/TXT/SOA). Use it to explain, not to repeat, the exposure result.
3. `rdap` (registry data, registrant contacts are redacted by policy) then `whois` for registrar and dates. If they disagree, report both.
4. `dorks` returns search URLs; it sends nothing. Present them as things the user can open, not as findings.
5. `gdelt` with the organization name for news mentions. Headlines are leads: a name match is not proof of the same entity.

## IP

`ip` gives geolocation and ASN. Geolocation is approximate (often the ISP's, not the host's): say so. Look up the hostname it returns with `dns`. With keys: `search_shodan`, `search_abuseipdb`, `search_virustotal`.

## Organization

Find the primary domain from the user's input or ask; do not guess it from a name. Then run the domain workflow. Treat news hits (GDELT) as unverified until the user confirms the entity.

## Reading `exposure` output

- A grade is a point-in-time summary of four checks, not a compliance result or a vulnerability scan.
- `--checks` selections are not graded (`grade` is null). Say "not graded", do not invent a letter.
- A skipped TLS/header check means the target refused or did not answer; report it as skipped.

## Citation examples

- Good: `DMARC policy is p=none [exposure example.com, email check]`
- Bad: `The company has weak email security.` (no source, overstated)
