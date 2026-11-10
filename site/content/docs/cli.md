---
title: "CLI reference"
label: "CLI reference"
seo_title: "OpenOSINT CLI reference: every subcommand and flag"
description: "Every openosint subcommand and global flag: keyless commands (dns, whois, rdap, ip, gdelt, dorks, exposure), keyed tools, web and REPL commands."
group: Reference
order: 8
---
Run `openosint` with no arguments for the interactive REPL. Run `openosint COMMAND` for a direct call with no AI provider involved. Put global flags (such as `--json` and `--allow-active`) **before** the subcommand: `openosint --json dns example.com`.

## Keyless commands

These need no API key and no AI provider. They are passive unless the Level column says otherwise.

| Command | What it does | Level |
|---|---|---|
| `openosint dns DOMAIN [-t N]` | A, AAAA, MX, NS, TXT, SOA records plus SPF and DMARC. DKIM selector probing needs `--allow-active` | passive |
| `openosint whois DOMAIN [-t N]` | WHOIS registration data | passive |
| `openosint rdap DOMAIN [-t N]` | RDAP registrar, dates, name servers, status | passive |
| `openosint ip ADDRESS [-t N]` | Geolocation, ASN, hostname via ipinfo.io. `IPINFO_TOKEN` is optional and raises the rate limit | passive |
| `openosint gdelt QUERY [-t N]` | Recent geolocated news mentions from GDELT | passive |
| `openosint dorks TARGET` | Builds Google dork URLs and sends nothing | passive |
| `openosint exposure DOMAIN [options]` | External exposure report graded A to F; see [Exposure report](/docs/exposure/) | email and registration passive; TLS and headers touch the target |

Options for `exposure`:

| Option | Meaning |
|---|---|
| `--json` | Structured JSON |
| `--report PATH.html` | Also write a self-contained HTML report |
| `--lang {en,it}` | Report language, with `--report` |
| `--lookalikes` | Also look for registered typo, homoglyph and TLD-swap domains (DNS only, never graded) |
| `--resolver IP` | Recursive resolver for lookups outside the domain's own nameservers |
| `--checks NAMES` | Run only `email`, `registration`, `tls`, `http_headers`. A selection is not graded |
| `--public-only` | Refuse targets that resolve to non-public addresses and vet every redirect hop; for hosted use |

Real output for several of these is on the [Quickstart](/docs/quickstart/).

## Keyed commands

Each needs the API key named in [Configuration](/docs/configuration/).

| Command | Needs | What it does |
|---|---|---|
| `openosint shodan QUERY [-t N]` | `SHODAN_API_KEY` | IP gives a host lookup; anything else is a banner or keyword search |
| `openosint virustotal TARGET [-t N]` | `VIRUSTOTAL_API_KEY` | IP, domain, URL or file hash |
| `openosint censys TARGET [-t N]` | `CENSYS_API_ID`, `CENSYS_SECRET` | IP gives a host view; a domain gives a certificate search |
| `openosint abuseipdb IP [-t N]` | `ABUSEIPDB_API_KEY` | Abuse confidence score and reports |
| `openosint ip2location IP [-t N]` | `IP2LOCATION_API_KEY` | Geolocation, ISP, VPN, proxy, Tor and datacenter flags |
| `openosint github QUERY [-t N]` | `GITHUB_TOKEN` (optional) | Profile, repos, commit-discovered emails, or a keyword search |
| `openosint search-dorks-live TARGET [--max-dorks N] [-t N]` | Bright Data key and SERP zone | Live Google results for dork queries. Default 5, max 12; each is billable |
| `openosint footprint TARGET [--max-queries N] [-t N]` | Bright Data key and SERP zone | Entity-type-aware search-engine footprint. Default 3 queries, each billable |
| `openosint scrape URL [-t N]` | Bright Data key and Unlocker zone | Fetch a URL through Bright Data Web Unlocker as Markdown. Touches the target |

Bright Data is the provider behind the last three: [get an account](%%BRIGHTDATA_LINK_DOCS%%). This is a referral link: OpenOSINT earns a commission if you sign up through it, at no extra cost to you.

## Active commands

These are noisy and off by default. They need the local binary installed and `--allow-active` (or `OPENOSINT_ALLOW_ACTIVE=1`). See [Safety](/docs/safety/).

| Command | Binary | What it does |
|---|---|---|
| `openosint --allow-active email ADDRESS [-t N]` | `holehe` | Services with an account on that email |
| `openosint --allow-active username HANDLE [-t N]` | `sherlock` | The handle across hundreds of platforms |

## Sessions, servers and helpers

| Command | What it does |
|---|---|
| `openosint` or `openosint shell` | Interactive AI REPL |
| `openosint web [--port N] [--host H] [--no-browser] [--allow-remote]` | Local browser UI; see [Web UI](/docs/web-ui/) |
| `openosint multi TARGETS` | Investigate several targets in parallel (AI). `TARGETS` is a comma-separated list or a file with one target per line; the maximum is 10 |
| `openosint playbook RECIPE TARGET` | Run a fixed investigation recipe with no AI. `RECIPE` is a name such as `domain` or a YAML file |
| `openosint history [--all] [--last N] [open N \| clear]` | List, open or delete saved REPL sessions |
| `openosint proxy-test` | Fetch your exit IP through the configured proxy |
| `openosint setup brightdata` | Guided setup for the Bright Data tools: checks your token, lists or creates the SERP API and Web Unlocker zones, saves them to `config.env`. Interactive only; asks before every change |
| `openosint config import [--from PATH] [--only KEY,...] [--yes]` | Copy settings from a `.env` into `~/.openosint/config.env` after confirmation |
| `openosint sponsors` | List current sponsors and featured integrations |
| `openosint-mcp [--allow-active]` | The [MCP server](/docs/mcp/) (a separate executable) |

## Global flags

| Flag | Meaning |
|---|---|
| `--allow-active` | Enable active tools (noisy, or they touch the target). Off by default; same as `OPENOSINT_ALLOW_ACTIVE=1` |
| `--json` | Structured JSON output |
| `-v`, `--verbose` | Debug logging to stderr |
| `--parallel` | Run complementary tools concurrently |
| `--no-pdf` | Do not write a PDF report |
| `--proxy URL` | Route requests through an upstream proxy |
| `--provider {anthropic,ollama,openai}` | AI provider for the REPL and `multi` (default `anthropic`) |
| `--api-key KEY` | Anthropic API key (overrides the environment) |
| `--ollama-model MODEL`, `--ollama-host URL` | Ollama model (default `llama3.2`) and server (default `http://localhost:11434`) |
| `--openai-base-url URL`, `--openai-model MODEL`, `--openai-api-key KEY` | An OpenAI-compatible endpoint (env: `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_API_KEY`) |

The per-command `-t SECONDS` / `--timeout` flag overrides that command's timeout.

## REPL commands

Inside the REPL, type a target (an email, username, domain, IP or name) and the agent picks and chains the tools.

| Command | Description |
|---|---|
| `<target>` | Investigate any target |
| `clear` | Reset conversation memory |
| `save` | Save the last report to `reports/` |
| `tools` | List available tools and their status |
| `config` | Show the current configuration |
| `history` | Browse saved sessions |
| `help` | Show all commands |
| `exit` or Ctrl-D | Exit |

Sessions are saved to `~/.openosint/history/`. For an OpenAI-compatible backend:

```bash
pip install "openosint[openai]"
openosint --provider openai \
  --openai-base-url http://localhost:4000/v1 \
  --openai-model gpt-4o-mini
```
