mcp-name: io.github.OpenOSINT/openosint

<div align="center">
  <img src="docs/logo.svg" alt="OpenOSINT" width="200" />
  <h1>OpenOSINT</h1>
  <p><strong>AI-powered OSINT agent. Interactive REPL · CLI · MCP Server · Web UI</strong></p>
  <p>16 tools. Powered by Anthropic Claude or local Ollama. For authorized security research only.</p>
</div>

<div align="center">

[![Release](https://img.shields.io/github/v/release/OpenOSINT/OpenOSINT?style=flat-square)](https://github.com/OpenOSINT/OpenOSINT/releases)
[![PyPI](https://img.shields.io/pypi/v/openosint?style=flat-square)](https://pypi.org/project/openosint/)
[![PyPI downloads](https://img.shields.io/pypi/dm/openosint?style=flat-square&label=PyPI%20downloads)](https://pypi.org/project/openosint/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square)](https://www.python.org/)
[![License MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
> See [DISCLAIMER.md](./DISCLAIMER.md) for legal and ethical use information.
[![MCP](https://img.shields.io/badge/protocol-MCP-blueviolet?style=flat-square)](https://modelcontextprotocol.io/)
[![MCP Registry](https://img.shields.io/badge/MCP_Registry-published-blueviolet?style=flat-square)](https://registry.modelcontextprotocol.io/servers/io.github.OpenOSINT/openosint)
[![GitHub Stars](https://img.shields.io/github/stars/OpenOSINT/OpenOSINT?style=flat-square)](https://github.com/OpenOSINT/OpenOSINT/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/OpenOSINT/OpenOSINT?style=flat-square)](https://github.com/OpenOSINT/OpenOSINT/network/members)
[![Sponsored by IP2Location](https://img.shields.io/badge/sponsored%20by-IP2Location.io-FF6B35?style=flat-square)](https://www.ip2location.io)

</div>

<div align="center">
  <img src="assets/demo.gif" alt="OpenOSINT demo" width="700" />
</div>

> **Legal Disclaimer**: OpenOSINT is intended for **legal and authorized use only**.
> Users are solely responsible for ensuring their use complies with all applicable laws and regulations.
> The authors accept no liability for misuse. See [DISCLAIMER.md](DISCLAIMER.md).

## What is OpenOSINT?

OpenOSINT is an AI agent for Open Source Intelligence with three interfaces: an interactive terminal REPL, a direct CLI, and an MCP server exposable to Claude Code, Claude Desktop, or any MCP-compatible client — plus a browser-based Web UI added in v2.12.0. The AI layer uses Anthropic's native tool use API (or a local Ollama model): the model issues hard stops when it needs a tool, your code executes the real binary, the actual output goes back — hallucination in tool results is structurally impossible.

## Features

- **AI tool chaining** — the agent decides which of 16 tools to run, chains them based on findings, and compiles a structured report
- **16 modular tools** covering email, username, breach, WHOIS, IP, subdomain, dorks, paste, phone, Shodan, VirusTotal, Censys, IP2Location, AbuseIPDB, GitHub, and DNS
- **Anthropic + Ollama** — use Claude via API key or run fully offline with a local Ollama model
- **MCP server** — expose all tools natively to Claude Code and Claude Desktop
- **Parallel execution** — `--parallel` runs complementary tools concurrently via `asyncio.gather()`
- **PDF + Markdown reports** — auto-saved after every investigation; PDF export via `reportlab`
- **Session history** — all REPL sessions saved to `~/.openosint/history/`; browse with `openosint history`
- **Web UI** — browser-based AI chat with streaming output, tool cards, and light/dark theme toggle

## Installation

```bash
# Install from PyPI (recommended)
pip install openosint
```

```bash
# Or install from source
git clone https://github.com/OpenOSINT/OpenOSINT.git
cd OpenOSINT
pip install -e .
```

**External binaries** (must be in `PATH`):

| Binary | Purpose | Install |
|--------|---------|---------|
| `holehe` | Email account enumeration | `pip install holehe` |
| `sherlock` | Username enumeration (300+ platforms) | `pip install sherlock-project` |
| `sublist3r` | Subdomain enumeration | `pip install sublist3r` |
| `phoneinfoga` | Phone number intelligence | [Download binary](https://github.com/sundowndev/phoneinfoga/releases) |

If a binary is absent, the corresponding tool returns a descriptive error string. All other tools remain operational.

## Quick Start

```bash
# Interactive AI REPL (default)
openosint

# Web interface
openosint web

# Direct tool (no AI)
openosint email target@example.com
```

## Configuration

Store all keys in a `.env` file at the project root (copy `.env.example`). `python-dotenv` loads it automatically at startup.

| Variable | Tool | Required | Purpose |
|----------|------|----------|---------|
| `ANTHROPIC_API_KEY` | AI agent | Yes (or use Ollama) | Anthropic API key |
| `HIBP_API_KEY` | `search_breach` | Optional | HaveIBeenPwned v3 — [get one](https://haveibeenpwned.com/API/Key) |
| `IPINFO_TOKEN` | `search_ip` | Optional | ipinfo.io higher rate limits |
| `SHODAN_API_KEY` | `search_shodan` | Optional | Shodan API — [get one](https://account.shodan.io) |
| `VIRUSTOTAL_API_KEY` | `search_virustotal` | Optional | VirusTotal API v3 — [get one](https://www.virustotal.com/gui/my-apikey) |
| `IP2LOCATION_API_KEY` | `search_ip2location` | Optional | IP2Location.io enhanced IP intelligence — [get one](https://www.ip2location.io/pricing) *(sponsored)* |
| `CENSYS_API_ID` + `CENSYS_SECRET` | `search_censys` | Optional | Censys Search API — [get one](https://censys.io/account) |
| `ABUSEIPDB_API_KEY` | `search_abuseipdb` | Optional | AbuseIPDB v2 — [get one](https://www.abuseipdb.com/account/api) |
| `GITHUB_TOKEN` | `search_github` | Optional | GitHub API — raises rate limit from 60 to 5000 req/h — [get one](https://github.com/settings/tokens) |
| `SHERLOCKEYE_API_KEY` | `search_sherlockeye` | Optional | Sherlockeye API — [get one](https://app.sherlockeye.io/api) |

**Optional Python packages:**

| Package | Purpose | Install |
|---------|---------|---------|
| `ollama` | Local LLM backend (no API key) | `pip install ollama` *(Python client only — also install the [Ollama runtime](https://ollama.com))* |
| `shodan` | Shodan API client | `pip install shodan` |
| `reportlab` | PDF report export | `pip install reportlab` |
| `censys` | Censys API client | `pip install censys` |

## Tools

| Tool | Powered by | What it investigates |
|------|-----------|---------------------|
| `search_email` | holehe | Social accounts linked to an email address |
| `search_username` | sherlock | Username presence across 300+ platforms |
| `search_breach` | HaveIBeenPwned v3 API | Data breach exposure |
| `search_whois` | python-whois | Domain registrant and DNS info |
| `search_ip` | ipinfo.io | Geolocation, ASN, hostname |
| `search_domain` | sublist3r | Subdomain enumeration |
| `generate_dorks` | built-in | 12 targeted Google dork URLs (no network calls) |
| `search_paste` | psbdmp.ws | Pastebin dump mentions |
| `search_phone` | phoneinfoga | Carrier, country, line type |
| `search_shodan` | Shodan API | Open ports, banners, CVEs |
| `search_virustotal` | VirusTotal API v3 | Verdict from 70+ antivirus engines |
| `search_ip2location` | IP2Location.io API | Enhanced IP intel: VPN/Proxy/Tor/datacenter flags *(sponsored)* |
| `search_censys` | Censys Search API | Internet-facing infrastructure, certificates |
| `search_abuseipdb` | AbuseIPDB v2 API | IP abuse reputation: confidence score, reports, country, ISP |
| `search_github` | GitHub REST API | Profile, repos, commit-discovered emails, username/keyword search |
| `search_dns` | dnspython (built-in) | A/AAAA/MX/NS/TXT/CNAME/SOA records; SPF, DMARC, DKIM analysis |
| `search_sherlockeye` | Sherlockeye API | Reverse Lookup & AI-Powered OSINT: email, phone, IP, username, domain, CPF/CNPJ |

### search_email

Enumerates online services linked to an email address using [holehe](https://github.com/megadose/holehe).

```bash
openosint email target@example.com
openosint email target@example.com -t 60
```

```text
OSINT results for 'target@example.com':
[+] Spotify        https://open.spotify.com/user/target
[+] WordPress      https://wordpress.com/target
[+] Gravatar       https://gravatar.com/target
[+] Office365      email used
```

### search_username

Searches for a username across 300+ platforms using [sherlock](https://github.com/sherlock-project/sherlock).

```bash
openosint username johndoe99
openosint username johndoe99 -t 120
```

```text
OSINT results for username 'johndoe99':
[+] GitHub         https://github.com/johndoe99
[+] Twitter        https://twitter.com/johndoe99
[+] Reddit         https://reddit.com/user/johndoe99
```

### search_breach

Checks data breach exposure via [HaveIBeenPwned v3 API](https://haveibeenpwned.com/API/v3). Requires `HIBP_API_KEY`.

```text
Found in 2 breach(es) for 'target@example.com':
[+] LinkedIn (2016-05-05) — leaked: Email addresses, Passwords
[+] Adobe (2013-10-04) — leaked: Email addresses, Password hints
```

### search_whois

Retrieves WHOIS data for a domain using [python-whois](https://github.com/richardpenman/whois).

```text
WHOIS results for 'example.com':
[+] Registrar: ICANN
[+] Created: 1995-08-14
[+] Expires: 2024-08-13
[+] Name Servers: A.IANA-SERVERS.NET
```

### search_ip

Retrieves geolocation and ASN data via [ipinfo.io](https://ipinfo.io). Free tier: 50k/month.

```text
IP intelligence for '8.8.8.8':
[+] Hostname: dns.google
[+] Org: AS15169 Google LLC
[+] City: Mountain View, CA, US
```

### search_domain

Enumerates subdomains using [sublist3r](https://github.com/aboul3la/Sublist3r).

```text
Subdomains found for 'example.com':
[+] mail.example.com
[+] dev.example.com
[+] api.example.com
```

### generate_dorks

Generates 12 targeted Google dork URLs for any target. No network calls.

```text
Google dork URLs for 'johndoe':
[+] "johndoe" site:linkedin.com
    https://www.google.com/search?q=%22johndoe%22+site%3Alinkedin.com
[+] "johndoe" leaked OR breach OR dump
    https://www.google.com/search?q=%22johndoe%22+leaked+OR+breach+OR+dump
```

### search_paste

Searches Pastebin dumps via [psbdmp.ws](https://psbdmp.ws).

```text
Found in 3 paste(s) for 'target@example.com':
[+] https://pastebin.com/aB1cD2eF (2023-04-12)
[+] https://pastebin.com/xY3zA4bC (2022-11-08)
```

### search_phone

Gathers phone intelligence using [phoneinfoga](https://github.com/sundowndev/phoneinfoga). Use E.164 format.

```text
Phone intelligence for '+14155552671':
[+] Country: United States
[+] Carrier: AT&T
[+] Line type: Mobile
```

### search_shodan

Queries the [Shodan](https://shodan.io) API. IPv4 input → host lookup (open ports, org, CVEs). Any other query → banner/keyword search. Requires `SHODAN_API_KEY`.

```bash
openosint shodan 8.8.8.8
openosint shodan "apache port:80 country:DE"
openosint shodan 8.8.8.8 -t 30
```

```text
Shodan host intelligence for '8.8.8.8':
[+] IP: 8.8.8.8
[+] Org: Google LLC
[+] Country: United States
[+] Open ports: 53, 443
```

### search_virustotal

Checks an IP address, domain, URL, or file hash against [VirusTotal](https://www.virustotal.com)'s 70+ antivirus engines using API v3. Auto-detects input type. Requires `VIRUSTOTAL_API_KEY`.

```bash
openosint virustotal 8.8.8.8
openosint virustotal example.com
openosint virustotal https://example.com/path
openosint virustotal 44d88612fea8a8f36de82e1278abb02f
```

```text
[VirusTotal] Type: ip
[VirusTotal] ASN: AS15169 Google LLC
[VirusTotal] Malicious: 0
[VirusTotal] Harmless: 72
```

If any engine flags the target:

```text
[VirusTotal] Malicious: 3
FLAGGED AS MALICIOUS by 3 engines
```

### search_censys

Queries the [Censys](https://censys.io) API. IPv4 input → host view (open ports, services, ASN); domain input → certificate search (SANs, issuer, first/last seen). Requires `CENSYS_API_ID` and `CENSYS_SECRET`.

```bash
openosint censys 8.8.8.8
openosint censys example.com
```

```text
[Censys] IP: 8.8.8.8
[Censys] Open Ports: 53, 443, 853
[Censys] Services: DNS, HTTPS, DNS-over-TLS
[Censys] ASN: AS15169 Google LLC
[Censys] Country: United States
```

```text
[Censys] Domain: example.com
[Censys] Certificates Found: 12
[Censys] Issuer: Let's Encrypt
[Censys] SANs: example.com, www.example.com, api.example.com
```

### search_ip2location

Queries the [IP2Location.io](https://www.ip2location.io) API for enhanced IP intelligence: geolocation (country, region, city, coordinates, ZIP), ISP, domain, ASN, and — on the Security Plan — VPN, proxy, Tor exit node, and datacenter detection. Sponsored integration. Requires `IP2LOCATION_API_KEY`.

```bash
openosint ip2location 8.8.8.8
openosint ip2location 2001:4860:4860::8888
```

```text
[IP2Location] IP: 8.8.8.8
[IP2Location] Country: United States (US)
[IP2Location] Region: California
[IP2Location] City: Mountain View
[IP2Location] ISP: Google LLC
[IP2Location] ASN: AS15169 Google LLC
[IP2Location] VPN: No  |  Proxy: No  |  TOR: No  |  Datacenter: Yes
[IP2Location] Threat: clean
```

If a VPN, proxy, or Tor exit node is detected:

```text
FLAGGED: VPN/Proxy/Tor detected
```

### search_abuseipdb

Checks an IP address against the [AbuseIPDB](https://www.abuseipdb.com) v2 API for abuse reputation. Returns abuse confidence score (0–100%), total reports, country, ISP, domain, and last reported timestamp. Requires `ABUSEIPDB_API_KEY`.

```bash
openosint abuseipdb 198.51.100.1
openosint abuseipdb 198.51.100.1 -t 30
```

```text
Abuse intelligence for '198.51.100.1':

[AbuseIPDB] IP: 198.51.100.1
[AbuseIPDB] Abuse Confidence Score: 87%
[AbuseIPDB] Total Reports: 143
[AbuseIPDB] Country: US
[AbuseIPDB] ISP: Example ISP LLC
[AbuseIPDB] Domain: example-isp.net
[AbuseIPDB] Last Reported: 2026-05-20T14:33:00+00:00
⚠️  HIGH ABUSE CONFIDENCE — flagged by AbuseIPDB
```

The warning line only appears when `abuseConfidenceScore` exceeds 50%.

## Interfaces

### Interactive REPL

Run `openosint` with no arguments to start the AI-powered REPL:

```text
openosint > investigate target@example.com

  -> generate_dorks('target@example.com')
  -> search_email('target@example.com')
  Found: Spotify, WordPress, Gravatar, Office365

  -> search_breach('target@example.com')
  Found in 2 breaches: LinkedIn (2016), Adobe (2013)

  Report saved -> reports/2026-05-11_14-32-11_report.md
```

**REPL commands:**

| Command | Description |
|---------|-------------|
| `<target>` | Investigate any target — email, username, domain, IP, name |
| `clear` | Reset conversation memory |
| `save` | Save last report to `reports/` |
| `tools` | List available tools and their status |
| `config` | Show current configuration |
| `history` | Browse saved sessions |
| `help` | Show all commands |
| `exit` / Ctrl-D | Exit |

All sessions are auto-saved to `~/.openosint/history/`. Browse with `openosint history`.

### Web UI

Introduced in v2.12.0:

```bash
openosint web
# Opens http://localhost:8080 automatically
```

Browser-based AI chat interface with streaming tool output, inline result cards, light/dark theme toggle, and Ollama support for fully local inference. No API key required when using Ollama.

```bash
# Install web extras
pip install "openosint[web]"
openosint web

# Use Ollama for fully local inference (no API key)
# Step 1: install the Ollama runtime (separate from the Python library)
#   macOS/Linux:  curl -fsSL https://ollama.com/install.sh | sh
#   Windows:      https://ollama.com/download/windows
# Step 2: start Ollama and pull a model
ollama serve          # start in a terminal (runs automatically as a service on some platforms)
ollama pull llama3.2  # download the model (~2 GB)
# Step 3: launch OpenOSINT and switch to Ollama
openosint web
# Settings -> Ollama (local) -> set model to llama3.2
```

<div align="center">
  <strong>Web UI</strong> — launch with <code>openosint web</code><br/>
  <img src="assets/web-demo.gif" alt="OpenOSINT web UI demo" width="700" />
</div>

### MCP Server

Expose all 16 OpenOSINT tools to any MCP-compatible AI client. Once connected, Claude can natively invoke all 16 tools during conversations.

**Claude Code:**

```bash
claude mcp add openosint python /absolute/path/to/OpenOSINT/openosint/mcp_server.py
claude mcp list
```

**Claude Desktop** — add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "openosint": {
      "command": "python",
      "args": ["/absolute/path/to/OpenOSINT/openosint/mcp_server.py"]
    }
  }
}
```

**Agentic use via Claude Code:**

```text
$ claude
> Investigate target@example.com. Trace any username found
  across other platforms and compile a full report.
```

## Docker

```bash
# Build and run
docker compose up --build

# One-off command
docker compose run --rm openosint email target@example.com --json
```

Set `ANTHROPIC_API_KEY` (and optionally `HIBP_API_KEY`, `IPINFO_TOKEN`) in a `.env` file or export them before running `docker compose`. Reports are persisted to `./reports/` via a volume mount.

**DigitalOcean App Platform:** see [`.do/app.yaml`](.do/app.yaml) for App Platform configuration.

## CLI Reference

| Flag / Subcommand | Description |
|---|---|
| `openosint` | Interactive AI REPL (default) |
| `openosint web [--port N] [--no-browser]` | Launch browser UI |
| `openosint email ADDRESS [-t N]` | Direct email scan |
| `openosint username HANDLE [-t N]` | Direct username scan |
| `openosint shodan QUERY [-t N]` | Shodan lookup |
| `openosint virustotal TARGET [-t N]` | VirusTotal lookup |
| `openosint censys TARGET [-t N]` | Censys lookup |
| `openosint ip2location IP [-t N]` | IP2Location lookup |
| `openosint abuseipdb IP [-t N]` | AbuseIPDB reputation check |
| `openosint github QUERY [-t N]` | GitHub profile/repo/email discovery |
| `openosint dns DOMAIN [-t N]` | DNS records + email security analysis |
| `openosint multi TARGETS` | Parallel multi-target investigation (max 10) |
| `openosint history [--all] [open N] [clear]` | View/manage REPL session history |
| `-v, --verbose` | Enable debug logging to stderr |
| `-t, --timeout N` | Override subprocess timeout (seconds) |
| `--api-key KEY` | Anthropic API key (overrides env var) |
| `--parallel` | Run complementary tools concurrently |
| `--json` | Output results as structured JSON |
| `--provider {anthropic,ollama}` | AI provider (default: `anthropic`) |
| `--ollama-model MODEL` | Ollama model name (default: `llama3.2`) |
| `--ollama-host URL` | Ollama server URL (default: `http://localhost:11434`) |
| `--no-pdf` | Disable automatic PDF generation |

## Integrations

| Service | URL | Tool | Tier |
|---------|-----|------|------|
| IP2Location.io | https://www.ip2location.io | `search_ip2location` | Featured (sponsored) |
| HaveIBeenPwned | https://haveibeenpwned.com | `search_breach` | Community |
| ipinfo.io | https://ipinfo.io | `search_ip` | Community |
| Shodan | https://shodan.io | `search_shodan` | Community |
| VirusTotal | https://www.virustotal.com | `search_virustotal` | Community |
| Censys | https://censys.io | `search_censys` | Community |
| AbuseIPDB | https://www.abuseipdb.com | `search_abuseipdb` | Community |
| GitHub    | https://github.com        | `search_github`    | Community |
| Sherlockeye | https://sherlockeye.io  | `search_sherlockeye` | Community |

## Sponsor this project

OpenOSINT is used by OSINT practitioners, security researchers, and developers who are actively evaluating and adopting intelligence APIs. Every time a user configures a new integration, the documentation routes them directly to that provider's API sign-up page — putting sponsors in front of their target audience **at the moment of adoption**.

Community integrations in the table above are eligible to upgrade to a Featured Integration sponsorship. Email [openosint@yahoo.com](mailto:openosint@yahoo.com?subject=OpenOSINT%20Sponsorship%20Inquiry) if you'd like your API to be the recommended provider for its category.

### Sponsorship tiers

| Tier | Benefits |
|------|----------|
| **Featured Integration** | Recommended/default provider for a tool category; logo + badge in README, website, and docs; "Featured (sponsored)" label in the Integrations table; listed first among providers for that category |
| **Sponsor** | Logo + link in README, website, and release notes |
| **Supporter** | Listed on the [website sponsors page](https://openosint.tech/#sponsors) |

Sponsorship is arranged by inquiry — reach out for current rates.

### Current sponsors

[![Sponsored by IP2Location](https://img.shields.io/badge/sponsored%20by-IP2Location.io-FF6B35?style=flat-square)](https://www.ip2location.io)

**[IP2Location.io](https://www.ip2location.io)** — Enhanced IP geolocation and threat intelligence API. Powers the `search_ip2location` tool with VPN, proxy, Tor, and datacenter detection. *Featured Integration sponsor.*

---

To sponsor OpenOSINT, email [openosint@yahoo.com](mailto:openosint@yahoo.com?subject=OpenOSINT%20Sponsorship%20Inquiry) or [open an issue](https://github.com/OpenOSINT/OpenOSINT/issues). Full prospectus: [SPONSORS.md](SPONSORS.md).

## Contributing

Issues and pull requests are welcome. Please read [DISCLAIMER.md](DISCLAIMER.md) before contributing.

## Maintainer

**Tommaso Bertocchi**  
- X (personal): https://x.com/SonoTommy_  
- X (OpenOSINT): https://x.com/openosint_oss  
- LinkedIn: https://www.linkedin.com/company/openosintoss  
- Email: openosint@yahoo.com

## License

OpenOSINT is open source under the [MIT License](./LICENSE) — free for personal, academic, and open source use.

For commercial use in closed-source products, a separate license is required. → [Full details](./COMMERCIAL-LICENSE.md)

---

*For authorized security research only. See [DISCLAIMER.md](DISCLAIMER.md).*

*OpenOSINT v2.18.0 — May 30, 2026*

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=OpenOSINT/OpenOSINT&type=Date)](https://star-history.com/#OpenOSINT/OpenOSINT&Date)
