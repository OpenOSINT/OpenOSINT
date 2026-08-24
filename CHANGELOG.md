# Changelog

All notable changes to OpenOSINT are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
OpenOSINT adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.25.1] — 2026-08-24

### Breaking
- Client-supplied AI backend destinations (a request-supplied `openai_base_url`
  or a non-default `ollama_host` sent to `POST /api/chat` or
  `POST /api/openai/test`) are now **rejected by default** — see
  **GHSA-q6cw-g86h-m2cq** below. The shipped web UI does not currently send
  either field with a real value: its "OpenAI-compat" BYOK panel talks to
  providers directly from the browser and never reaches these endpoints, so
  this should not affect normal use of the bundled UI. If you have custom
  client code (browser extension, direct API integration, or a modified
  build) that relies on sending these fields to your own server, set
  `OPENOSINT_ALLOW_CLIENT_BACKEND=1` there to keep it working.

### Security
- **[GHSA-q6cw-g86h-m2cq]** `POST /api/chat` and `POST /api/openai/test`
  filled a missing `openai_api_key` from the server's `OPENAI_API_KEY`
  environment variable even when the destination `openai_base_url` came from
  the request body — a caller could point the base URL at an
  attacker-controlled host and receive the server's own credential in the
  `Authorization` header, along with the full conversation/tool-schema
  payload (credential theft + SSRF, including against cloud metadata
  endpoints). `/api/openai/test` additionally echoed the probe result back to
  the caller, making it a non-blind SSRF oracle for internal port scanning.
  Affects >= 2.19.0 (`openai_base_url`/`openai_api_key` request fields) and
  >= 2.23.0 (`/api/openai/test`), not just >= 2.25.0 as originally reported.
  - Client-supplied backend destinations are now off by default
    (`OPENOSINT_ALLOW_CLIENT_BACKEND`, unset). With it unset, a
    request-supplied `openai_base_url` or non-default `ollama_host` is
    rejected outright and the credential/destination coupling never has a
    chance to occur.
  - When the flag is enabled, destinations resolving to link-local
    (169.254.0.0/16, fe80::/10 — cloud metadata), multicast, IANA-reserved,
    or unspecified addresses are always rejected; loopback and RFC1918 are
    permitted (LAN Ollama / local llama.cpp use cases).
    `OPENOSINT_ALLOWED_BASE_URLS` is an optional strict per-host allowlist
    that overrides the IP checks and closes the DNS-rebinding TOCTOU window.
  - The server's environment-sourced API key is never sent to a
    client-supplied destination, under any circumstance — no fallback, ever.
  - Every outbound HTTP client now disables redirect-following explicitly,
    so a redirect from an allowed host cannot be used to reach a disallowed
    one.
  - A Sec-Fetch-Site / Origin browser guard (`OPENOSINT_ALLOWED_ORIGINS` for
    reverse-proxy setups) blocks cross-origin browser requests when the flag
    is enabled; curl/SDK/script callers, which send neither header, are
    unaffected.
  - Every rejection reachable from this path — flag disabled, malformed URL,
    disallowed destination, allowlist mismatch, or a rejected browser
    origin — returns an identical 403 response, so the response can't be
    used to fingerprint whether `OPENOSINT_ALLOW_CLIENT_BACKEND` is enabled
    on a given deployment.

## [2.25.0] — 2026-07-13

### Security
- **[GHSA-cqr4-hcfp-m6m4, CVSS 10.0]** `POST /api/setup` was reachable by any
  network caller and wrote arbitrary key/value pairs straight into
  `os.environ` and `.env` — including `OPENAI_BASE_URL`, letting a remote
  attacker redirect outbound chat traffic (and its auth header) to attacker
  infrastructure.
  - `/api/setup` now requires the caller be loopback, or present a token
    matching `OPENOSINT_SETUP_TOKEN` (unset by default — remote setup is
    off unless an operator opts in).
  - Replaced arbitrary key writes with an explicit allowlist; unknown keys
    are dropped and reported back.
  - `OPENAI_BASE_URL` is validated as a well-formed `http(s)` URL before
    being applied.
  - CLI/web server now default to a `127.0.0.1` bind and refuse `0.0.0.0`
    (or any non-loopback host) without `--allow-remote` /
    `OPENOSINT_ALLOW_REMOTE=1`.
  - Thanks to **@avishaigo-commits** and **@yotampe-pluto** for the report.

### Added
- **Web UI: live entity-graph panel** — client-side graph view of
  investigation results (Cytoscape-based renderer), with a BYOK settings
  panel, browser-side agent loop, and provider adapters for
  Anthropic/OpenAI-compatible/Ollama backends.
- **Deterministic investigation playbooks** — `domain`, `ip`, and `person`
  recipes that chain tool calls into a repeatable, formatted report without
  relying on the AI agent's judgment for step ordering.
- **Global upstream-proxy support** — HTTP/SOCKS5 proxy configuration for
  all web-facing tools.

---

## [2.20.0] — 2026-06-11

### Added
- **Bright Data integration** — two new optional tools backed by the [Bright Data](https://get.brightdata.com/984ni58s2oad?utm_source=github&utm_medium=changelog) API. Both tools require `BRIGHTDATA_API_KEY` and gracefully degrade (descriptive error string, no exception) when the key is absent. Free tier: 5,000 requests/month.
  - `search_dorks_live` — executes the same Google dork templates as `generate_dorks` through the Bright Data SERP API, returning structured results (title, URL, snippet) for each query. Runs up to 5 dorks by default; each is a separate billable call. `generate_dorks` is unchanged and remains fully offline.
  - `scrape_url` — fetches any public URL through the Bright Data Web Unlocker API (bypasses Cloudflare/CAPTCHA) and returns clean Markdown via the API's native `data_format: "markdown"` conversion. A general primitive the AI agent can chain after other tools.
- Both tools are wired into all four interfaces: **REPL** (agent tool-use), **CLI** (`openosint search-dorks-live <target>`, `openosint scrape <url>`), **MCP server** (`search_dorks_live`, `scrape_url` tools), and **Web UI** (tool catalog with availability indicator).
- New env vars: `BRIGHTDATA_API_KEY`, `BRIGHTDATA_SERP_ZONE`, `BRIGHTDATA_UNLOCKER_ZONE` — added to `.env.example` and README Configuration table.
- Unit tests (`tests/test_brightdata.py`): success, failure, and missing-key cases for both tools, all HTTP calls mocked.

---

## [2.19.1] — 2026-06-09

### Fixed
- Use absolute `raw.githubusercontent.com` URLs for logo and terminal demo images so they render correctly on the PyPI project page (PyPI's renderer does not resolve relative paths).

---

## [2.19.0] — 2026-06-05

### Added
- **OpenAI-compatible backend** (`--provider openai`). OpenOSINT can now drive any
  endpoint that speaks the OpenAI `/v1/chat/completions` protocol — LiteLLM,
  llama-swap, vLLM, LM Studio, etc. — via the new `OpenAICompatibleAgent`.
  - CLI flags: `--openai-base-url`, `--openai-model`, `--openai-api-key`.
  - Env vars: `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`. When
    `OPENAI_BASE_URL` is set (and no `ANTHROPIC_API_KEY`), it takes precedence
    over Ollama.
  - Web UI: new "OpenAI API" backend option with base-URL/model/key fields and a
    connection test; streaming tool-use via the new `_stream_openai` handler.
  - The target model must support tool/function calling (for llama.cpp behind
    llama-swap, launch with `--jinja`).
  - 68 unit tests covering all new code paths (100% on `OpenAICompatibleAgent`,
    `_select_chat_backend`, `_stream_openai`, and CLI/REPL routing).

### Fixed
- `OpenAICompatibleAgent`: empty `choices` server response now returns a descriptive
  error instead of a bare `"list index out of range"` exception.

## [2.18.1] — 2026-06-02

### Fixed

- Fix: resolve binaries installed in the same venv/uv-tool bin so co-installed tools
  (`holehe`, `phoneinfoga`, `sherlock`, `sublist3r`) are found instead of throwing a spurious
  `ToolNotFoundError`. `run_subprocess()` now prepends the running interpreter's `bin/` directory
  to `PATH` before exec. Fix by [@consocio](https://github.com/consocio) ([#6](https://github.com/OpenOSINT/OpenOSINT/pull/6)).

### Changed

- Version bumped to 2.18.1.

---

## [2.15.0] — 2026-05-25

### Added

- **DNS intelligence** (`openosint/tools/search_dns.py`): new tool `search_dns` that performs
  comprehensive DNS record enumeration (A, AAAA, MX, NS, TXT, CNAME, SOA) using dnspython.
  Automatically highlights email security misconfigurations: absent or permissive SPF policy,
  missing or unenforced DMARC, absent DKIM records across common selectors. No external API
  or credentials required. Available as CLI subcommand `openosint dns DOMAIN [-t SECONDS]`,
  in the AI agent tool loop, and as an MCP tool.
- **GitHub OSINT** (`openosint/tools/search_github.py`): new tool `search_github` that queries
  the GitHub REST API for a username, email, or keyword. For direct username matches returns
  full profile data (bio, location, company, follower counts, public repos/gists), the most
  recently updated repositories with language and star counts, and email addresses discovered
  from public commit history. For other queries returns the top 5 matching user accounts.
  Optional `GITHUB_TOKEN` environment variable raises the unauthenticated rate limit from
  60 to 5000 requests per hour. Available as CLI subcommand `openosint github QUERY [-t SECONDS]`,
  in the AI agent tool loop, and as an MCP tool.

### Changed

- Version bumped to 2.15.0.
- `dnspython>=2.6.0` added to core dependencies.
- Agent SYSTEM_PROMPT updated: domain investigations now suggest `search_dns` alongside
  `search_whois` and `search_domain`; GitHub username lookups use `search_github`.
- MCP server docstring updated to reflect 16 tools.
- README: tools table, CLI synopsis, and FILES section updated.

---

## [2.14.0] — 2026-05-24

### Added

- **AbuseIPDB integration** (`openosint/tools/search_abuseipdb.py`): new tool
  `search_abuseipdb` that checks an IP address against the AbuseIPDB v2 API.
  Returns abuse confidence score (0–100%), total reports, country, ISP, domain,
  and last reported timestamp. Displays a prominent ⚠️ HIGH ABUSE CONFIDENCE
  warning when score exceeds 50%. Validates IPv4/IPv6 input before calling the
  API; returns a descriptive error string for invalid input or missing credentials.
  Requires `ABUSEIPDB_API_KEY` environment variable. Available as CLI subcommand
  `openosint abuseipdb IP_ADDRESS [-t SECONDS]`, in the AI agent tool loop, and
  as an MCP tool.

### Changed

- Version bumped to 2.14.0 in `pyproject.toml`, `README.md`, MCP server docstring.
- `aiohttp>=3.9.0` added to core dependencies.

---

## [2.13.0] — 2026-05-21

### Changed

- Bumped version to 2.13.0

---

## [2.12.0] — 2026-05-21

### Added

- Web interface (`openosint web`) — browser-based AI chat UI
- Light/dark theme toggle in web UI
- Ollama support in web UI for local inference
- Demo recording script (`python media/record_demo.py`)
- Web demo GIF and MP4

### Changed

- README: added web interface demo at top, restructured header with tagline and centered layout
- Docs: added demo section with web and CLI demos side by side

---

## [2.11.0] — 2026-05-19

### Added

- **IP2Location integration** (`openosint/tools/search_ip2location.py`): new tool `search_ip2location` that queries the IP2Location.io API for enhanced IP intelligence. Returns geolocation (country, region, city, lat/lon, ZIP), ISP, domain, ASN, and security flags: VPN, proxy, Tor exit node, and datacenter hosting. Adds a prominent `⚠️  FLAGGED: VPN/Proxy/Tor detected` warning line when any flag is active. Validates IPv4 and IPv6 input with regex before calling the API; returns `"Invalid IP address format."` for non-IP strings. Requires `IP2LOCATION_API_KEY` environment variable; returns a descriptive error string if absent. Available as CLI subcommand `openosint ip2location IP_ADDRESS [-t SECONDS]`, in the AI agent tool loop, and as an MCP tool. Sponsored integration.
- **.env file support** (`python-dotenv`): `openosint/cli.py` now calls `load_dotenv()` at startup so users can store API keys in a `.env` file at the project root instead of exporting environment variables manually. `python-dotenv>=1.0.0` added to core dependencies in `pyproject.toml`.
- **.env.example template**: new `.env.example` file at the project root documents all supported environment variables with placeholder values. Copy to `.env` and fill in keys.

### Changed

- `.gitignore`: added `!.env.example` so the example template is tracked while `.env` and `*.env.*` remain excluded.
- README: tools table, optional env vars, and Integrations section updated to include `search_ip2location` and `IP2LOCATION_API_KEY`. Sponsored note added for IP2Location.

### Chore

- Version bumped to `2.10.0` in `pyproject.toml`, `README.md`, MCP server docstring.

---

## [2.9.0] — 2026-05-18

### Added

- **Censys integration** (`openosint/tools/search_censys.py`): new tool `search_censys` that queries the Censys Search API for internet-facing infrastructure data. Auto-detects input type: IPv4 address → `CensysHosts().view()` returning open ports, services, ASN, and country; domain → `CensysCerts().search()` with `parsed.names` filter returning certificate count, issuer, SANs, and first/last seen dates. Returns descriptive error strings for missing credentials, rate limits, and network errors. Requires `CENSYS_API_ID` and `CENSYS_SECRET` environment variables. Available as CLI subcommand `openosint censys TARGET [-t SECONDS]`, in the AI agent tool loop, and as an MCP tool.
- **Auto-detection of IP vs domain for Censys queries**: IPv4 pattern → host view; everything else → certificate search.

### Changed

- Version bumped to `2.9.0` in `pyproject.toml`, `README.md`, MCP server docstring.
- Agent `SYSTEM_PROMPT` updated to mention `search_censys` for IP and domain infrastructure investigations.
- README: tools table, optional env vars, optional packages, FILES section, and CLI synopsis updated to include `search_censys`.
- `pyproject.toml`: added `censys>=2.2.0` as optional dependency under `[project.optional-dependencies]` `censys` and `all` extras.

### Docs

- Updated `README.md` tools table and env vars with `search_censys`, `CENSYS_API_ID`, `CENSYS_SECRET`.
- Added Integrations table to `README.md`.

---

## [2.8.0] — 2026-05-17

### Refactor

- Full clean code pass across the entire codebase: consistent naming conventions (`is_/has_/can_` booleans, verb-prefixed functions, no abbreviations), extracted module-level constants, split functions exceeding 20 lines into focused helpers, added type hints to every public signature.
- Extracted shared subprocess execution logic into `openosint/utils.py` (`run_subprocess`, `SubprocessResult`) — eliminates duplication across four tool modules.
- `agent.py`: extracted `_AgentRunContext` dataclass, `_extract_first_text`, `_execute_tool`, `_process_tool_turn`, `_process_ollama_tool_turn`, and `_build_ollama_assistant_message` helpers; `_MAX_TOKENS = 4096` constant; both agent `run()` methods reduced to ≤25 lines.
- `pdf_report.py`: split `_generate_pdf_sync` (~100 lines) into `_build_pdf_styles`, `_build_pdf_story`, `_create_footer_callback`.
- `search_whois.py`: synchronous WHOIS call now wrapped in `asyncio.wait_for` + `run_in_executor` for real timeout support; `timeout_seconds` parameter added to `run_whois_osint`.
- All tools: explicit `timeout_seconds` propagated through agent `_TOOL_MAP` and MCP `_HANDLERS`.
- `repl.py`, `cli.py`, `mcp_server.py`, `multi_target.py`: `no_pdf` → `is_pdf_disabled`; `parallel` → `is_parallel`; silent `except Exception: pass` blocks replaced with `logger.debug(..., exc_info=True)`.

### Chore

- All health checks passing: ruff, pytest (99+ tests), pip check, bandit.
- Version bumped to `2.8.0` in `pyproject.toml`, `README.md`, banner, MCP server docstring.
- `asyncio_default_fixture_loop_scope = "function"` added to `[tool.pytest.ini_options]`.

---

## [2.7.0] — 2026-05-16

### Added

- **VirusTotal integration** (`openosint/tools/search_virustotal.py`): new tool `search_virustotal` that checks IP addresses, domains, URLs, and file hashes (MD5/SHA-1/SHA-256) against VirusTotal's 70+ antivirus engines using the VirusTotal API v3. Auto-detects input type and calls the appropriate endpoint (`/ip_addresses`, `/domains`, `/urls` + `/analyses` polling, `/files`). Returns country, ASN, registrar, file type, analysis stats (malicious/suspicious/harmless/undetected votes), and a prominent warning line when `malicious > 0`. Requires `VIRUSTOTAL_API_KEY` environment variable; returns a descriptive error string if absent. Available as CLI subcommand `openosint virustotal TARGET [-t SECONDS]`, in the AI agent tool loop, and as an MCP tool.
- **Auto-detection of input type for VirusTotal queries**: IPv4 pattern → IP lookup, `^[0-9a-fA-F]{32|40|64}$` → file hash lookup, `http(s)://` prefix → URL scan (submit + poll), everything else → domain lookup.

### Changed

- Version bumped to `2.7.0` in `pyproject.toml`, `README.md`.

### Chore

- `pyproject.toml` description updated to reflect 11 tools.

---

## [2.6.0] — 2026-05-15

### Added

- **Persistent session history** (`openosint/session_history.py`): each REPL session is automatically saved to `~/.openosint/history/<timestamp>_session.json` when the session ends (normal exit, Ctrl-D, or crash). Each file records the timestamp, duration, prompts typed, tools used, targets investigated, and report path — no raw tool output or API keys are ever stored. At most 50 sessions are retained; the oldest file is deleted when the limit is exceeded.
- **`openosint history` CLI command**: lists the last 10 sessions in a Rich table (columns: #, date, duration, targets, tools used, report). Supports `--all` to show all sessions, `--last N` to show the last N, `openosint history open N` to view the full session JSON plus report contents in a Rich panel, and `openosint history clear` to delete all history with a confirmation prompt.
- **Session count hint in REPL banner**: if saved sessions exist, a one-line hint is shown at startup — `💾 N sessions saved — type 'history' to browse`. The `history` REPL command displays the last 10 sessions inline.

### Changed

- Version bumped to `2.6.0` in `pyproject.toml`, `README.md`, and REPL banner.

---

## [2.5.0] — 2026-05-13

### Added

- **Star prompt in REPL banner**: the welcome banner now prints a one-time star prompt to stderr — `⭐ If OpenOSINT is useful, star it → https://github.com/OpenOSINT/OpenOSINT` — using Rich with a yellow star emoji and dim URL. Printed to stderr only; never appears in CLI subcommand output or MCP server responses.

### Changed

- Version bumped to `2.5.0` in `pyproject.toml`, `README.md`, and REPL banner.

### Chore

- Removed AI model attribution from contributor metadata so only the human author appears in the GitHub contributor graph.

---

## [2.4.0] — 2026-05-13

### Added

- **Shodan integration** (`openosint/tools/search_shodan.py`): new tool `search_shodan` that performs host lookups (`api.host()`) for IP addresses or keyword banner searches (`api.search()`) for any other query. Requires `SHODAN_API_KEY` environment variable; returns a descriptive error string if absent. Available as CLI subcommand `openosint shodan QUERY [-t SECONDS]`, in the AI agent tool loop, and as an MCP tool.
- **Ollama support** (`--provider ollama`): the AI agent loop now works with local Ollama models — no Anthropic API key required. Use `--provider ollama` (default: `llama3.2`), `--ollama-model MODEL`, and `--ollama-host URL`. The `OllamaAgent` in `agent.py` follows the same tool-use loop as the Anthropic agent: tool call → execute real binary → feed real output back → repeat until done. Requires `pip install ollama` (optional dependency).
- **PDF report export** (`openosint/pdf_report.py`): every investigation that auto-saves a Markdown report now also generates a matching PDF (`reports/YYYY-MM-DD_HH-MM-SS_report.pdf`) using `reportlab`. The PDF includes a branded header, clean body text with monospace tool output sections, and a footer with page numbers. Generation is non-blocking (runs in a thread executor). Use `--no-pdf` to disable. Falls back silently with a log warning if `reportlab` is not installed.
- **Multi-target investigation** (`openosint/multi_target.py`): new `openosint multi TARGETS` CLI subcommand and `investigate_multi` MCP tool. Accepts a comma-separated list of targets or a path to a file with one target per line. All targets are investigated in parallel via `asyncio.gather()`. Each gets its own report file (`reports/YYYY-MM-DD_target_report.md`); a consolidated summary is written to `reports/YYYY-MM-DD_summary.md`. Maximum 10 targets per run.
- **New CLI flags**: `--provider`, `--ollama-model`, `--ollama-host`, `--no-pdf`.
- **REPL**: banner now shows the active provider and model. `config` command shows provider, Ollama host, and PDF status.
- **Test suite** (`tests/test_v240.py`): tests covering missing Shodan API key, IP detection helper, multi-target 10-target limit, target parsing from files and inline strings, and PDF file creation.

### Changed

- Version bumped to `2.4.0` in `pyproject.toml`, `README.md`, REPL banner, and MCP server header.
- Agent tool definitions and `_TOOL_MAP` updated to include `search_shodan`.
- `[project.optional-dependencies]` in `pyproject.toml` now includes `shodan`, `ollama`, `pdf`, and `all` extras.

---

## [2.3.0] — 2026-05-12

### Added

- **Parallel tool execution** (`--parallel` CLI flag): independent complementary tools now run concurrently via `asyncio.gather()`. For the `email` subcommand, `search_email` and `search_breach` execute in parallel. For the `username` subcommand, `search_username` and `search_paste` execute in parallel. Sequential execution remains the default for backward compatibility.
- **JSON export** (`--json` CLI flag): all direct CLI commands can now output results as structured JSON instead of formatted text. Each result follows a consistent schema: `{ "tool", "target", "timestamp", "results", "error" }`.
- **MCP JSON output parameter**: each MCP tool now accepts an optional `json_output` boolean parameter. When `true`, the tool response is returned in the same structured JSON schema used by the CLI.
- **`openosint/json_output.py`**: new internal module exposing `format_tool_result()` and `to_json()` helpers, importable by both CLI and MCP server.
- **Docker support**: added `Dockerfile` (based on `python:3.12-slim`) and `docker-compose.yml` to the repository root. The image installs `holehe`, `sherlock-project`, and `sublist3r` via pip, and mounts `./reports/` as a volume.
- **Test suite** (`tests/test_json_export.py`): pytest tests covering the JSON export schema for all 9 tool names, line splitting, blank-line filtering, error field handling, and ISO-8601 timestamp format.

### Changed

- Version bumped to `2.3.0` in `pyproject.toml`, `README.md`, `repl.py` banner, `mcp_server.py` header, and `search_breach.py` user-agent string.
- CLI status/progress messages now go to `stderr` so that `--json` stdout output is clean and pipeable.

---

## [2.2.0] — 2026-05-11

### Added

- Project documentation website (`docs/`) with landing page, logo, sitemap, and robots.txt.
- `docs/CNAME` for custom domain support on GitHub Pages.

### Changed

- README rewritten in man-page style with full per-tool documentation, architecture table, and example output blocks.
- `index.html` iteration with improved layout and copy.

---

## [2.1.0] — 2026-05-10

### Added

- Interactive REPL (`openosint/repl.py`) powered by `prompt_toolkit` and `Rich` — the default mode when running `openosint` with no arguments.
- Auto-save: structured reports with a `##` header longer than 300 characters are automatically written to `reports/<timestamp>_report.md`.
- REPL built-in commands: `clear`, `save`, `tools`, `config`, `help`, `exit`.
- `search_paste` tool: searches Pastebin dumps via psbdmp.ws API.
- `search_phone` tool: wraps the `phoneinfoga` binary for carrier and country intelligence.
- `generate_dorks` tool: generates 12 targeted Google dork URLs locally (no network calls).
- Agent system prompt with explicit investigation strategy and chaining rules.
- `openosint/exceptions.py`: shared exception hierarchy (`OSINTError`, `ToolNotFoundError`, `ToolExecutionError`, `ToolTimeoutError`).
- MCP server (`openosint/mcp_server.py`) exposing all 9 tools to Claude Code and Claude Desktop.

### Changed

- Model updated to `claude-sonnet-4-20250514`.
- All tool modules return descriptive error strings on failure rather than raising — callers (CLI, MCP, agent) never need to catch tool-level exceptions.

---

## [2.0.0] — 2026-05-08

### Added

- Initial public release of OpenOSINT v2.
- Core tool set: `search_email` (holehe), `search_username` (sherlock), `search_breach` (HIBP v3 API), `search_whois` (python-whois), `search_ip` (ipinfo.io), `search_domain` (sublist3r).
- AI agent loop (`openosint/agent.py`) using the Anthropic native tool use API.
- Direct CLI subcommands: `email`, `username`.
- `pyproject.toml` PEP 621 build configuration with `openosint` entry point.
- MIT license.

[2.9.0]: https://github.com/OpenOSINT/OpenOSINT/releases/tag/v2.9.0
[2.7.0]: https://github.com/OpenOSINT/OpenOSINT/releases/tag/v2.7.0
[2.6.0]: https://github.com/OpenOSINT/OpenOSINT/releases/tag/v2.6.0
[2.5.0]: https://github.com/OpenOSINT/OpenOSINT/releases/tag/v2.5.0
[2.4.0]: https://github.com/OpenOSINT/OpenOSINT/releases/tag/v2.4.0
[2.3.0]: https://github.com/OpenOSINT/OpenOSINT/releases/tag/v2.3.0
[2.2.0]: https://github.com/OpenOSINT/OpenOSINT/releases/tag/v2.2.0
[2.1.0]: https://github.com/OpenOSINT/OpenOSINT/releases/tag/v2.1.0
[2.0.0]: https://github.com/OpenOSINT/OpenOSINT/releases/tag/v2.0.0
