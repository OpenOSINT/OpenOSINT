---
name: osint
description: Passive open-source reconnaissance and external exposure checks for a domain, IP address or organization, using OpenOSINT (DNS, RDAP, WHOIS, email authentication, TLS, security headers, news mentions, search dorks). Use when the user asks to investigate, profile, recon or "look up" a domain, IP or company, or to check what a domain exposes to the internet. No API keys needed for the default flow.
license: MIT
compatibility: Needs uv (for `uvx`) and network access. Optional API keys unlock more tools.
argument-hint: "<domain | IP | organization>"
---

# OpenOSINT: passive recon

Invoked as `/osint <target>`: investigate the target below with the chain that fits it and write the Markdown report described at the end. If no target was given, ask for one.

Target: $ARGUMENTS

OpenOSINT runs real tools in Python and returns their real output. You orchestrate and summarize; you never invent results.

## Rules (read first)

1. **Passive by default.** Run only passive tools. Never pass `--allow-active`, never set `OPENOSINT_ALLOW_ACTIVE`, never use `scrape`, `username`, `email` or subdomain brute-force unless the user explicitly asks for that tool by name. If an active tool would help, say so and ask.
2. **Authorization.** Only investigate targets the user owns or is authorized to assess. If the target looks like a private individual, stop and ask what the legitimate purpose is. OpenOSINT is not designed for people search.
3. **Every finding cites its tool call.** Write each finding as `claim [tool: args]`, e.g. `SPF is missing [exposure example.com]`. No citation, no finding.
4. **Summaries are leads, not proof.** Say "indicates" or "suggests", never "confirms". Report what a tool returned, not what you infer from it. Flag tool errors and empty results as such; never fill gaps from memory.
5. **Missing key: say which one.** If a tool reports a missing key, do not skip it silently and do not retry. Tell the user the variable to set (see [references/keys.md](references/keys.md)).

## How to call tools

Use the CLI first: it needs no API key, no AI provider and no MCP server, so it works on any agent. Put `--json` before the subcommand:

```bash
uvx --from openosint==2.38.0 openosint --json exposure example.com
uvx --from openosint==2.38.0 openosint --json dns example.com
uvx --from openosint==2.38.0 openosint --json rdap example.com
uvx --from openosint==2.38.0 openosint --json whois example.com
uvx --from openosint==2.38.0 openosint --json dorks example.com
uvx --from openosint==2.38.0 openosint --json gdelt "Example Corp"
uvx --from openosint==2.38.0 openosint --json ip 8.8.8.8
uvx --from openosint==2.38.0 openosint --json exposure example.com --checks email,registration
```

- `--json` output has `tool`, `target`, `timestamp`, `results` and `error`; cite those.
- `exposure` grades A-F. Its TLS and header checks connect to the target on port 443; `--checks email,registration` never touches the target (use it when the user wants zero contact). `--report PATH.html` writes a printable report.
- `dorks` only builds search URLs and sends nothing.
- `ip` queries ipinfo.io; it works unkeyed at low volume, and `IPINFO_TOKEN` raises the limit.

Use the MCP tools (`search_whois`, `search_rdap`, `search_gdelt_geo`, `generate_dorks`, `search_ip`, and the keyed ones) only when the `openosint` MCP server is already connected. They return the same data. Do not emulate a tool with `whois` or `curl`.

## What to chain

| Target | Chain (all keyless, passive) |
|---|---|
| Domain | `exposure` → `dns` → `rdap` → `whois` → `dorks` → `gdelt` (org name) |
| IP | `ip` → `dns` on the hostname it returns |
| Organization | Resolve its main domain first, run the Domain chain, then `gdelt` on the org name |

Keyed extras, offer only when they add something: `search_shodan`, `search_censys`, `search_virustotal` (domain/IP/hash), `search_abuseipdb`, `search_breach`. Details and variable names: [references/keys.md](references/keys.md).

Order and interpretation hints: [references/workflows.md](references/workflows.md).

## Report format

Markdown, in this order: **Target and scope** (what was run, what was deliberately not), **Findings** (one bullet per finding with its citation), **Not checked / needs a key**, **Leads to verify**. Keep tool errors visible in the report.
