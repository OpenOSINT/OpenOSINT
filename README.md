mcp-name: io.github.OpenOSINT/openosint

<div align="center">
  <img src="https://raw.githubusercontent.com/OpenOSINT/OpenOSINT/v2.19.1/docs/logo.svg" alt="OpenOSINT" width="200" />
  <h1>OpenOSINT</h1>
  <p><strong>AI-powered OSINT agent. Interactive REPL · CLI · MCP Server · Web UI</strong></p>
  <p>18 tools. Works natively with <strong>Claude Code</strong>, <strong>Claude Desktop</strong>, and any MCP-compatible client (Cursor, Windsurf, …). Powered by Anthropic Claude, local Ollama, or any OpenAI-compatible endpoint. For authorized security research only.</p>
  <p>New to OSINT? Start here → <a href="https://openosint.tech/learn">openosint.tech/learn</a></p>
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
[![Backers](https://opencollective.com/openosint_oss/backers/badge.svg)](https://opencollective.com/openosint_oss)
[![Sponsors](https://opencollective.com/openosint_oss/sponsors/badge.svg)](https://opencollective.com/openosint_oss)

<a href="https://opencollective.com/openosint_oss"><img src="https://opencollective.com/openosint_oss/donate/button@2x.png?color=blue" alt="Donate to OpenOSINT on Open Collective" width="200" /></a>

</div>

<div align="center">
  <img src="https://raw.githubusercontent.com/OpenOSINT/OpenOSINT/v2.19.1/assets/demo.gif" alt="OpenOSINT terminal demo" width="900" />
</div>

```bash
pip install openosint
```

- **18 modular tools** — email, username, IP, domain, WHOIS, breach, phone, paste, Shodan, VirusTotal, Censys, AbuseIPDB, GitHub, DNS, live dork search, and URL scraping
- **MCP server built in** — expose all 18 tools natively to Claude Code, Claude Desktop, and any MCP-compatible client; no extra config needed
- **Three AI backends** — Anthropic Claude (default), local Ollama, or any OpenAI-compatible endpoint; tool results come from real subprocess calls, never hallucinated
- **Fully async** — parallel tool execution via `asyncio.gather()` with hard subprocess timeouts
- **MIT licensed** — no embedded LLM; bring your own API key or run fully offline

---

> **Legal Disclaimer**: OpenOSINT is intended for **legal and authorized use only**.
> Users are solely responsible for ensuring their use complies with all applicable laws and regulations.
> The authors accept no liability for misuse. See [DISCLAIMER.md](DISCLAIMER.md).

## Sponsors

<table>
<tr>
<td align="center" valign="top" width="200">
<a href="https://www.ip2location.com" rel="noopener sponsored">
<img src="https://raw.githubusercontent.com/OpenOSINT/OpenOSINT/main/docs/assets/ip2location-logo.png" alt="IP2Location — IP geolocation and threat intelligence provider" width="140">
</a><br>
<sub><b>IP2Location</b></sub><br>
<sub>IP Geolocation &amp; IP Intelligence</sub><br>
<sub><em>Enhanced IP geolocation, ISP, VPN/Proxy/Tor detection.</em></sub>
</td>
<td valign="top">
<b>Your logo here</b><br>
<sub>Open: <b>proxy detection</b> · <b>breach data</b> · <b>threat intel</b> · <b>email/identity</b></sub><br>
<sub>One vendor per category — exclusive placement across README, docs, CLI, and Web UI.</sub><br><br>
<sub><a href="https://openosint.tech/sponsors.html">Media kit &amp; pricing →</a> · <a href="https://opencollective.com/openosint_oss">Open Collective</a> · <a href="mailto:openosint@yahoo.com?subject=OpenOSINT%20Sponsorship%20Inquiry">openosint@yahoo.com</a></sub>
</td>
</tr>
</table>

## Custom Integrations

Need OpenOSINT wired into your SOC, fraud, threat-intel, or AI-agent stack?
I build bespoke OSINT & MCP integrations for teams — you bring the data
sources and compliance requirements, I deliver a working integration.

→ **[Get in touch](mailto:openosint@yahoo.com?subject=OpenOSINT%20Custom%20Integration)**

---

## What is OpenOSINT?

OpenOSINT is an AI agent for Open Source Intelligence with three interfaces: an interactive terminal REPL, a direct CLI, and an MCP server exposable to Claude Code, Claude Desktop, or any MCP-compatible client — plus a browser-based Web UI added in v2.12.0. The AI layer uses Anthropic's native tool use API (or a local Ollama model, or any OpenAI-compatible endpoint): the model issues hard stops when it needs a tool, your code executes the real binary, the actual output goes back — hallucination in tool results is structurally impossible.

## Features

- **AI tool chaining** — the agent decides which of 18 tools to run, chains them based on findings, and compiles a structured report
- **18 modular tools** covering email, username, breach, WHOIS, IP, subdomain, dorks, paste, phone, Shodan, VirusTotal, Censys, IP2Location, AbuseIPDB, GitHub, DNS, live dork search, and URL scraping
- **Anthropic, Ollama, or any OpenAI-compatible endpoint** — use Claude via API key, run fully offline with a local Ollama model, or point at any OpenAI-compatible server (LiteLLM, llama-swap, vLLM, LM Studio, …)
- **MCP server** — expose all tools natively to Claude Code and Claude Desktop
- **Parallel execution** — `--parallel` runs complementary tools concurrently via `asyncio.gather()`
- **PDF + Markdown reports** — auto-saved after every investigation; PDF export via `reportlab`
- **Session history** — all REPL sessions saved to `~/.openosint/history/`; browse with `openosint history`
- **Web UI** — browser-based AI chat with streaming output, tool cards, and light/dark theme toggle

## 🧠 From tools to method — AI OSINT Prompt Pack

OpenOSINT gives you the tooling. The **AI OSINT Prompt Pack** gives you the *method*: 30+ tested prompts that make ChatGPT / Claude **collect → pivot → verify** against real public sources instead of hallucinating.

- Email, username, domain, IP, phone, company due-diligence, image & reporting prompts
- One repeatable investigation flow + an ethics & legal primer
- 7-page PDF · instant download · pairs directly with OpenOSINT

**→ [Get the Prompt Pack](https://buy.polar.sh/polar_cl_0sipbBYjR01q4d9leCAtepteFDSGkPfy1TKoV3wIgkr?utm_source=github&utm_medium=readme&utm_campaign=promptpack)**

_Buying it directly funds OpenOSINT's development. 🙏_

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
| `ANTHROPIC_API_KEY` | AI agent | Yes (or use Ollama / OpenAI) | Anthropic API key |
| `OPENAI_BASE_URL` | AI agent | Optional | Base URL of an OpenAI-compatible endpoint (e.g. `http://localhost:4000/v1`). When set and `ANTHROPIC_API_KEY` is absent, it is used as the AI backend (takes precedence over Ollama). The model must support tool/function calling. |
| `OPENAI_API_KEY` | AI agent | Optional | API key for the OpenAI-compatible endpoint (local servers may ignore it) |
| `OPENAI_MODEL` | AI agent | Optional | Model name to request from the endpoint (default: `gpt-4o-mini`) |
| `HIBP_API_KEY` | `search_breach` | Optional | HaveIBeenPwned v3 — [get one](https://haveibeenpwned.com/API/Key) |
| `IPINFO_TOKEN` | `search_ip` | Optional | ipinfo.io higher rate limits |
| `SHODAN_API_KEY` | `search_shodan` | Optional | Shodan API — [get one](https://account.shodan.io) |
| `VIRUSTOTAL_API_KEY` | `search_virustotal` | Optional | VirusTotal API v3 — [get one](https://www.virustotal.com/gui/my-apikey) |
| `IP2LOCATION_API_KEY` | `search_ip2location` | Optional | IP2Location.io enhanced IP intelligence — [get one](https://www.ip2location.io/pricing) *(sponsored)* |
| `CENSYS_API_ID` + `CENSYS_SECRET` | `search_censys` | Optional | Censys Search API — [get one](https://censys.io/account) |
| `ABUSEIPDB_API_KEY` | `search_abuseipdb` | Optional | AbuseIPDB v2 — [get one](https://www.abuseipdb.com/account/api) |
| `GITHUB_TOKEN` | `search_github` | Optional | GitHub API — raises rate limit from 60 to 5000 req/h — [get one](https://github.com/settings/tokens) |
| `BRIGHTDATA_API_KEY` | `search_dorks_live`, `scrape_url` | Optional | Bright Data API key — [get one](https://get.brightdata.com/984ni58s2oad?utm_source=github&utm_medium=readme)¹ (free tier: 5,000 req/month). |
| `BRIGHTDATA_SERP_ZONE` | `search_dorks_live` | Optional | Your Bright Data SERP API zone name (e.g. `serp_api1`). Create one in the [Bright Data dashboard](https://get.brightdata.com/984ni58s2oad?utm_source=github&utm_medium=readme)¹. |
| `BRIGHTDATA_UNLOCKER_ZONE` | `scrape_url` | Optional | Your Bright Data Web Unlocker zone name (e.g. `web_unlocker1`). Create one in the [Bright Data dashboard](https://get.brightdata.com/984ni58s2oad?utm_source=github&utm_medium=readme)¹. |

**Optional Python packages:**

| Package | Purpose | Install |
|---------|---------|---------|
| `ollama` | Local LLM backend (no API key) | `pip install ollama` *(Python client only — also install the [Ollama runtime](https://ollama.com))* |
| `openai` | OpenAI-compatible backend for the REPL/CLI (`--provider openai`) | `pip install "openosint[openai]"` *(not required for the Web UI, which has no extra dependency)* |
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
| `search_dorks_live` | Bright Data SERP API | Live Google search results for dork queries (title, URL, snippet) |
| `scrape_url` | Bright Data Web Unlocker | Fetch any URL bypassing Cloudflare/CAPTCHA — returns clean Markdown |

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

### search_dorks_live

Executes live Google dork queries for a target through the [Bright Data SERP API](https://get.brightdata.com/984ni58s2oad?utm_source=github&utm_medium=readme)¹, returning structured results (title, URL, snippet) for each dork. Reuses the same templates as `generate_dorks` — the offline tool remains unchanged. Each dork is a separate billable API call; defaults to 5 dorks per run. Requires `BRIGHTDATA_API_KEY` and `BRIGHTDATA_SERP_ZONE`.

```bash
openosint search-dorks-live "john doe"
openosint search-dorks-live "target@example.com" --max-dorks 3
openosint search-dorks-live example.com --max-dorks 5 -t 30
```

```text
Bright Data live dork search for 'john doe' (5 queries):

[+] Dork: "john doe"
    Title:   John Doe — LinkedIn
    URL:     https://www.linkedin.com/in/johndoe
    Snippet: Software engineer with 10 years of experience...

[+] Dork: "john doe" site:linkedin.com
    Title:   John Doe | LinkedIn
    URL:     https://www.linkedin.com/in/john-doe-12345
    ...
```

### scrape_url

Fetches any public URL through the [Bright Data Web Unlocker API](https://get.brightdata.com/984ni58s2oad?utm_source=github&utm_medium=readme)¹, bypassing Cloudflare, CAPTCHA, and other bot-protection mechanisms. Returns clean Markdown using the API's native `data_format: "markdown"` conversion. A general primitive the AI agent can chain after discovering URLs with other tools. Requires `BRIGHTDATA_API_KEY` and `BRIGHTDATA_UNLOCKER_ZONE`.

```bash
openosint scrape https://example.com
openosint scrape https://protected-site.com -t 60
```

```text
[Web Unlocker] URL: https://example.com
[Web Unlocker] Remote status: 200

# Example Domain

This domain is for use in illustrative examples in documents.
You may use this domain in literature without prior coordination or asking for permission.
...
```

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

Browser-based AI chat interface with streaming tool output, inline result cards, light/dark theme toggle, and support for fully local inference via Ollama or any OpenAI-compatible endpoint. No Anthropic API key required when using a local backend.

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

# Or point at any OpenAI-compatible endpoint (LiteLLM, llama-swap, vLLM, LM Studio, …).
# The selected model must support tool/function calling.
export OPENAI_BASE_URL="http://localhost:4000/v1"
export OPENAI_API_KEY="sk-..."        # optional for local servers
export OPENAI_MODEL="gpt-4o-mini"
openosint web
# Settings -> OpenAI API  (or just start chatting — it is auto-selected when no ANTHROPIC_API_KEY is set)
```

For the REPL/CLI, the same backend is available via `--provider openai`:

```bash
pip install "openosint[openai]"
openosint --provider openai \
  --openai-base-url http://localhost:4000/v1 \
  --openai-model gpt-4o-mini
```

> **llama.cpp users:** If your llama.cpp server returns HTTP 400 errors, add
> `--openai-raw-socket` to use an alternative TCP socket transport that
> works around a compatibility issue with httpx's default HTTP stack:
>
> ```bash
> openosint --provider openai \
>   --openai-base-url http://localhost:8000/v1 \
>   --openai-model Qwen3.6-35B-A3B-Q4_K_M-GGUF \
>   --openai-raw-socket
> ```

<div align="center">
  <strong>Web UI</strong> — launch with <code>openosint web</code>
</div>

---

### Live Documentation

The interactive documentation at [openosint.tech](https://openosint.tech/) covers every tool, CLI flag, and configuration option.

<div align="center">
  <img src="https://raw.githubusercontent.com/OpenOSINT/OpenOSINT/v2.19.1/assets/demo-web.gif" alt="openosint.tech documentation tour" width="900" />
</div>

### MCP Server

Expose all 18 OpenOSINT tools to any MCP-compatible AI client. Once connected, Claude can natively invoke all 18 tools during conversations.

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
| `--provider {anthropic,ollama,openai}` | AI provider (default: `anthropic`) |
| `--ollama-model MODEL` | Ollama model name (default: `llama3.2`) |
| `--ollama-host URL` | Ollama server URL (default: `http://localhost:11434`) |
| `--openai-base-url URL` | OpenAI-compatible endpoint base URL (env: `OPENAI_BASE_URL`) |
| `--openai-model MODEL` | Model to request from the endpoint (default: `gpt-4o-mini`; env: `OPENAI_MODEL`) |
| `--openai-api-key KEY` | API key for the endpoint (env: `OPENAI_API_KEY`) |
| `--openai-raw-socket` | Use raw TCP socket transport (workaround for llama.cpp HTTP 400 issues) |
| `--no-pdf` | Disable automatic PDF generation |

## Integrations

| Service | URL | Tool | Tier | Auth |
|---------|-----|------|------|------|
| IP2Location.io | https://www.ip2location.io | `search_ip2location` | Featured (sponsored) | API key — free tier |
| AbuseIPDB | https://www.abuseipdb.com | `search_abuseipdb` | Community | API key — free tier |
| Censys | https://censys.io | `search_censys` | Community | API key — free tier |
| GitHub | https://github.com | `search_github` | Community | Token optional |
| HaveIBeenPwned | https://haveibeenpwned.com | `search_breach` | Community | API key — paid |
| holehe | https://github.com/megadose/holehe | `search_email` | Community | None — local binary |
| ipinfo.io | https://ipinfo.io | `search_ip` | Community | Token optional |
| phoneinfoga | https://github.com/sundowndev/phoneinfoga | `search_phone` | Community | None — local binary |
| psbdmp.ws | https://psbdmp.ws | `search_paste` | Community | None |
| sherlock | https://github.com/sherlock-project/sherlock | `search_username` | Community | None — local binary |
| Shodan | https://shodan.io | `search_shodan` | Community | API key — free tier |
| sublist3r | https://github.com/aboul3la/Sublist3r | `search_domain` | Community | None — local binary |
| VirusTotal | https://www.virustotal.com | `search_virustotal` | Community | API key — free tier |
| WHOIS (IANA) | https://www.iana.org/whois | `search_whois` | Community | None |
| DNS (system resolver) | — | `search_dns` | Community | None |
| Google Search | https://www.google.com | `generate_dorks` | Community | None |

## Resources

- **[AI OSINT Prompt Pack](https://buy.polar.sh/polar_cl_0sipbBYjR01q4d9leCAtepteFDSGkPfy1TKoV3wIgkr?utm_source=github&utm_medium=readme&utm_campaign=promptpack)** — 30+ ready-to-use prompts for faster, ethical OSINT investigations with any AI assistant. Built to pair with OpenOSINT.

## Sponsor this project

OpenOSINT is used by OSINT practitioners, security researchers, and developers actively evaluating intelligence APIs. Every time a user configures an integration, the docs route them to that provider's sign-up page — high-intent exposure at the moment of adoption.

**Featured Integration** ($2,000/year or $220/month): recommended/default provider for one tool category, exclusive. Logo + badge across README, docs, CLI banner, and Web UI. One vendor per category.

Open categories: **proxy detection** · **breach/credential data** · **threat & domain intel** · **email/identity lookup**

→ Full media kit and pricing: [openosint.tech/sponsors.html](https://openosint.tech/sponsors.html)

### Current sponsors

<!-- SPONSORS:START -->

<a href="https://www.ip2location.io/?utm_source=openosint&utm_medium=readme&utm_campaign=featured" rel="noopener sponsored">
<img src="https://raw.githubusercontent.com/OpenOSINT/OpenOSINT/main/docs/assets/ip2location-logo.png" alt="IP2Location" width="140">
</a>

**[IP2Location.io](https://www.ip2location.io/?utm_source=openosint&utm_medium=readme&utm_campaign=featured)** — Featured Integration · IP Geolocation & IP Intelligence

Enhanced IP geolocation, ISP, VPN/Proxy/Tor, and datacenter detection. Powers `search_ip2location`.

<!-- SPONSORS:END -->

[Open Collective](https://opencollective.com/openosint_oss) · [openosint@yahoo.com](mailto:openosint@yahoo.com?subject=OpenOSINT%20Sponsorship%20Inquiry) · [SPONSORSHIP.md](SPONSORSHIP.md)

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow, integration registration checklist, and coding conventions. Please read [DISCLAIMER.md](DISCLAIMER.md) before contributing.

## Maintainer

**Tommaso Bertocchi**  
- X (personal): https://x.com/SonoTommy_  
- X (OpenOSINT): https://x.com/openosint_oss  
- LinkedIn: https://www.linkedin.com/company/openosintoss  
- Email: openosint@yahoo.com

## Contributors

| Contributor | Contribution |
|---|---|
| [@consocio](https://github.com/consocio) | venv/uv-tool binary resolution fix — co-installed tools are now found without a separate activation step ([#6](https://github.com/OpenOSINT/OpenOSINT/pull/6)) |


## SERVICES

The framework is free and MIT-licensed. This is an optional paid setup service offered by the maintainer.

**OSINT-MCP Setup Sprint** — done-for-you installation and configuration of an autonomous OSINT-MCP pipeline on your environment. Fully async, no calls required.

**Includes:**
- Pre-configured OpenOSINT setup tailored to your stack (Claude Code, Claude Desktop, or any MCP client)
- API keys wired in (Shodan, VirusTotal, IP2Location, HaveIBeenPwned, and others as needed)
- One investigation workflow built around your use case
- Written step-by-step setup guide + screen-recorded walkthrough
- 1-page runbook
- Async email support for 7 days

**Delivery:** 3–5 days, fully async.

**For:** SOC analysts · threat-intel teams · fraud/AML · pentesters · OSINT investigators

**Founding pricing** available for early teams — inquire.

→ Email [openosint@yahoo.com](mailto:openosint@yahoo.com) · [LinkedIn](https://www.linkedin.com/company/openosintoss) · <!-- INTAKE_FORM_LINK -->

*For authorized use only. See [DISCLAIMER.md](DISCLAIMER.md).*

## License

OpenOSINT is open source under the [MIT License](./LICENSE) — free for personal, academic, and open source use.

For commercial use in closed-source products, a separate license is required. → [Full details](./COMMERCIAL-LICENSE.md)

---

¹ Bright Data links in this README are affiliate/referral links — OpenOSINT earns a commission if you sign up through them, at no extra cost to you.

*For authorized security research only. See [DISCLAIMER.md](DISCLAIMER.md).*

*OpenOSINT v2.22.0 — June 2026*

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=OpenOSINT/OpenOSINT&type=Date)](https://star-history.com/#OpenOSINT/OpenOSINT&Date)
