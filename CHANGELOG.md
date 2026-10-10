# Changelog

All notable changes to OpenOSINT are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
OpenOSINT adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

## [2.33.0] — 2026-10-10

OpenOSINT is now passive by default. Agents and MCP clients are only offered tools that query third-party data sources or compute locally; noisy and target-touching tools are an explicit opt-in. Every agent loop has a per-request tool-call cap, every tool carries a noise label (web UI, tool descriptions, README table), and the docs no longer claim that hallucination is impossible.

> ### ⚠ Behavior changes
>
> **OpenOSINT is now passive by default, everywhere** (CLI, REPL, web UI, MCP server, Cloud gateway, playbooks, `investigate_graph`).
> Agents and MCP clients are only offered tools that query third-party data sources or compute locally. These tools are **off until you opt in**:
> `search_username`, `search_email`, `search_domain` (noisy), `scrape_url` (touches the target), `search_phone` (unverified), VirusTotal **URL submission** (VirusTotal fetches the URL and the community can see it), and the 9 DKIM selector probes inside `search_dns`.
>
> **To restore the old behavior:** pass `--allow-active` (CLI/REPL/web/MCP server), set `OPENOSINT_ALLOW_ACTIVE=1`, or use Settings → "Enable active tools" in the web UI. A public or demo instance can never enable them.
>
> Direct CLI subcommands (`openosint username …`, `email`, `scrape`) now exit with code 2 and a message unless `--allow-active` is given.
>
> **Every agent loop is now capped at 15 tool calls per user request** (`OPENOSINT_MAX_TOOL_CALLS`; each new message resets it), and `investigate_multi` shares one cap of 30 across all targets (`OPENOSINT_MAX_TOOL_CALLS_MULTI`). When the cap is reached the investigation stops with an explicit message. Before this, the Anthropic, Ollama and OpenAI-compatible agent loops had no limit.

### Added

- `openosint/tool_policy.py`: one classification per tool (`passive` / `touches target` / `noisy` / `unverified` / `inherits`) with an honest one-line note, used by every surface. A test fails if a registered tool has no label.
- Noise labels in the web UI Settings tool list, in tool descriptions sent to agents and MCP clients, and in a generated README table.
- `--allow-active` (CLI, `openosint-mcp`), `OPENOSINT_ALLOW_ACTIVE`, `POST /api/policy` and a Settings toggle.
- Disabled tools return a structured `disabled_in_passive_mode` result explaining how to enable them.
- `GET /api/policy` (mode, cap, list of active tools).

### Changed

- `search_dns` no longer runs DKIM selector probes in passive mode and says so in its output.
- `investigate_graph` routes only to passive tools in passive mode and spends the same per-request cap.
- README, docs and the hallucination article no longer claim that hallucination is "structurally impossible". The accurate claim: tool results come from real executions and every finding is shown with the tool call that produced it; the model can still misread or misattribute them, and AI output is a lead, not proof.
- `search_domain` is no longer described as "passive": it scrapes search engines and aggregators from your IP.

### Removed

- RapidProxy is no longer listed as a sponsor (README, SPONSORSHIP.md, docs pages, `sponsors.json`); its integration page and logo assets are deleted.

### Fixed

- The Ollama and OpenAI-compatible agent loops (CLI/REPL and web chat) could loop on tool calls with no bound.
- sherlock's OSINTSearch promotion no longer appears in `search_username` results. Credit to the underlying tools stays: `search_username`, `search_email` and `search_domain` results now end with "Results via sherlock / holehe / sublist3r (project URL)".
- In demo mode on a loopback bind (`OPENOSINT_DEMO_MODE`), `restriction_reason` no longer says "this instance is not bound to loopback"; it reports the real reason, in `/api/health`, `/api/policy` and the Settings UI.

## [2.32.0] — 2026-10-09

Live geolocated news is back on the globe, via GDELT's 15-minute GKG feed (the GDELT GEO API was retired). Headlines now show on globe points, results accumulate across searches, the globe flies to new results, and the Globe nav shows an "N places" badge. Also fixes the news-before-globe race, the blank coverage pill, the dropped bounding box, and the Alpine warning on user messages.

> **New environment variables** (all optional): `OPENOSINT_GDELT_WINDOW_HOURS` (default `6`, max `24`), `OPENOSINT_GDELT_MAX_ARTICLES` (default `30000`), `OPENOSINT_GDELT_USE_PROXY` (default off).

### Changed
- `search_gdelt_geo` works again: the GDELT GEO 2.0 API it called was retired (HTTP 404), so it now reads GDELT's 15-minute GKG article feed (`data.gdeltproject.org`, keyless) and keeps a rolling window in memory (default 6 hours; `OPENOSINT_GDELT_WINDOW_HOURS`, hard cap `OPENOSINT_GDELT_MAX_ARTICLES`, oldest dropped first). Same tool name, same GeoJSON point shape and `[service_unavailable]` result. Query matching is against headlines and URLs (`"phrases"`, `OR`, `*`), country-level mentions are dropped, and points now carry `title`, `url`, `domain` and `tone`.
- Lazy and polite: nothing is downloaded until the tool is first used. The first search loads only the newest file; older files load on one background thread, one download at a time. Upstream load is one file per 15 minutes regardless of how many searches run. The result and the globe say how far back they cover ("News: last 15 min — older articles still loading").
- Downloads are fail-closed: https `data.gdeltproject.org` only, no redirects, compressed and decompressed size caps, per-field length caps, URL validation; any violation returns the structured service-unavailable result.
- The globe shows the headline and domain of a news point as plain text; box-select now asks for query `"*"` in the selected area, and a search with no matches clears the previous search's dots.

- Globe: news accumulates per conversation across searches, the camera flies to new results, and the Globe nav shows an "N places" badge (cleared with the trash icon).

### Fixed
- News that arrived before the globe was first opened was lost; the coverage pill could render blank; the Alpine warning on every user message (`msg.parts` on messages without parts) is gone.
- `POST /api/run/search_gdelt_geo` dropped the selected bounding box; `RunRequest` now accepts an optional 4-number `bbox` (HTTP 422 if malformed) and passes it to the tool.

### Added
- Opt-in live check: `OPENOSINT_LIVE=1 pytest tests/test_gdelt_geo_live.py`.

## [2.31.0] — 2026-10-06

Keys saved on this computer from the web UI, a first-run panel, clear messages for tools that need a key, the graph store and MCP graph tools without native builds, a new `search_rdap` tool, and a graceful fallback when the GDELT GEO service is down.

> **Behavior changes**
> - Keys saved from the web UI now go to `$OPENOSINT_HOME/config.env` (default `~/.openosint/config.env`, user-only permissions) instead of `<package root>/.env`. Precedence is real environment > `config.env` > legacy `.env`. A legacy package-root `.env` that would have been loaded is copied once, with a stderr notice (keys named, never values); the old file stays and keeps working.
> - A key saved in the UI while a real environment variable of the same name is set is stored but reported as not active (the environment wins on every start).
> - `/api/setup` now throttles repeated non-loopback attempts (HTTP 429) and its 403 explains the Docker case. The loopback / `OPENOSINT_SETUP_TOKEN` rules are unchanged.
> - Tool count is 21 (`search_rdap`).

### Added
- Graph store without native builds: `openosint.graph.ftm_compat` re-exports followthemoney when it imports and otherwise uses vendored `make_entity_id` / `Statement` / property types that produce byte-identical ids (enforced by a CI parity job against the real library). The `/graph` page, `/api/graph/*`, `graph_neighbors` and `graph_review_candidates` now work on a plain `uvx openosint web`; `graph_export` and dedup still need the `graph` / `graph-dedup` extras and say so.
- `search_rdap`: keyless RDAP domain registration lookup (registrar, dates, name servers, status) in the agent, MCP server and web UI.
- `GET /api/setup/status`, a settings catalog, a first-run panel (dismissible; what works with no keys, one-step AI provider, Ollama as the free local option) and a key form that lists every supported key, grouped, with where to get each.
- `OPENOSINT_SETUP_TOKEN` is passed through `docker-compose.yml`; the UI has a token field.
- CI: vendored-id parity job (`REQUIRE_FTM=1`, fails instead of skipping), key-survives-restart check on the `uvx` path, and Docker checks for the blocked-setup message and the token path.

### Changed
- Web UI Settings on a local install now leads with "Save on this computer" (all keys, grouped, including the OpenAI-compatible endpoint), which writes through `/api/setup` to `config.env`; the browser-only provider and tool-key fields moved behind "Use only for this browser session (not saved)". Each key shows whether it is configured (never its value) and whether an environment variable overrides a saved value. The public demo keeps browser-only keys and its copy unchanged.

### Fixed
- "Save to server" in the web UI did nothing: it iterated `this.apiKeys`, which was never defined. A 403 now shows the server's explanation instead of "Save failed".
- Every credentialed tool now returns one structured message when its key is missing (`Scan error` line, `[key_required] VAR, VAR`, a link per key, where to put it) and names all missing variables at once (Censys ID+secret, Bright Data key+zone). Sponsor and referral links carry UTM parameters.
- The keyless rate limiter now covers `search_github`, `search_email`, `search_username` and `search_domain`, and also guards `/api/stream/{tool}`, which bypassed it.
- The web UI reported holehe/sherlock/sublist3r as unavailable when installed next to OpenOSINT (the `uvx` case) because it searched only `PATH`; it now uses the same lookup as the tools. Missing-binary messages give the exact `uv tool install` command.
- Tests no longer read or write the developer's real `~/.openosint`.
- `search_gdelt_geo` now returns a clear "service unavailable" result when the GDELT GEO API fails (404, 429, 5xx, timeouts, malformed responses), and the globe shows a notice instead of failing silently.

## [2.30.0] — 2026-10-01

One-command install (`uvx openosint web`), Docker fixes, and CI that now runs on Ubuntu, macOS and Windows.

> **Behavior changes**
> - Docker now publishes the web UI on `127.0.0.1:8080` by default instead of all host interfaces. To expose it deliberately, run `OPENOSINT_BIND=0.0.0.0 docker compose up` (see the README Docker section for the security note).
> - `openosint web` exits with a clear message when the port is busy instead of printing a URL and then a raw uvicorn error.

### Added
- One-command web UI install: `uvx openosint web` (after installing [uv](https://docs.astral.sh/uv/)). The README Installation section now leads with it; `pip install openosint && openosint web` remains the documented fallback.
- `OPENOSINT_HOME` environment variable to relocate the data directory (`graph.db`, session history). Defaults to `~/.openosint`, so existing installs are unchanged; `OPENOSINT_GRAPH_DB` still takes precedence for `graph.db`.
- `openosint web` banner now prints the data directory and, when no AI provider is configured, a one-line notice. No network probe is made to print it.
- CI workflow `install-check`: tests and lint on Python 3.10 and 3.12, a clean `uvx` install (no keys, isolated HOME) with web and MCP health checks on Ubuntu, macOS and Windows, the graph extra on Ubuntu, and `docker compose up` on a fresh checkout with no `.env`.

### Changed
- `openosint web` binds its port before printing the URL or opening the browser. If the port is busy it exits with `Port N is already in use. Pick another one with: openosint web --port N+1` instead of printing a URL and then a raw uvicorn error.
- Docker: `.env` is now optional in `docker-compose.yml` (a fresh clone previously failed or created a directory named `.env`). The image installs the `graph` extra instead of `web` (which only added `playwright`), stores `graph.db` and history in an `openosint-data` volume via `OPENOSINT_HOME=/data`, and keeps UI-saved keys in that volume. A new `.dockerignore` keeps a local `.env` and `.venv` out of the image.
- **Behavior change:** `docker-compose.yml` now publishes the web UI on `127.0.0.1:8080` instead of all host interfaces. The setup endpoint accepts API keys, so LAN exposure should be deliberate: run `OPENOSINT_BIND=0.0.0.0 docker compose up` (see the README Docker section for the security note). Anyone reaching the container from another machine must set `OPENOSINT_BIND`.
- The MCP server's `serverInfo.version` now reports the OpenOSINT version (it reported the `mcp` library's version).
- 7 graph tests that exercise unimplemented `NotImplementedError` stubs are marked `xfail` (non-strict) so the suite is green.
- Package description says 20 tools, matching the tool catalog.
- Docker: `docker-compose.yml` sets `OPENOSINT_PUBLISHED_BIND` (derived from `OPENOSINT_BIND`) so a port published on loopback only is no longer treated as network-exposed, and defaults `OPENOSINT_ALLOWED_HOSTS=localhost,127.0.0.1` so the `Host` check is active. Only an exact `127.0.0.1`, `localhost` or `::1` lifts the restriction; unset, empty or anything else keeps it. The banner says when it is lifted. Never set it by hand when the port is reachable from other interfaces.
- Docker: `/app/.env` is a symlink to `/data/.env` that is no longer pre-created empty, so a fresh container logs no `Loaded .env` line until a key is saved.

### Fixed
- `/api/sponsors` returned 500 on pip/wheel installs because `sponsors.json` was not packaged. The file now lives at `openosint/sponsors.json` (still the single source of truth, also read by `scripts/render_sponsors.py`) and ships in the wheel; a missing file falls back to an empty list.
- `.mcp/server.json` described 16 tools; it now says 20, and the docs-consistency test checks it.

### Removed
- `.do/app.yaml` (DigitalOcean App Platform spec, unused).

## [2.29.1] — 2026-10-01

### Security
- Fixed: the local web server could be driven by any website open in the same browser while `openosint web` was running (advisory: [GHSA-2wrv-jxxj-r2xc](https://github.com/OpenOSINT/OpenOSINT/security/advisories/GHSA-2wrv-jxxj-r2xc)). The server now validates the `Host` header and refuses cross-site browser requests to every `/api/*` endpoint except `/api/health`, and `/api/setup` requires `Content-Type: application/json`. All users of the web UI should upgrade. The MCP server, CLI and REPL are not affected.
- New settings: `OPENOSINT_ALLOWED_HOSTS` (extra hostnames the server answers to; also the way to turn on `Host` checking on `--allow-remote` and Docker binds) and `OPENOSINT_ALLOWED_ORIGINS` (extra browser origins allowed to call the API). See the README Web UI section.
- Behavior change: reaching the UI through a name other than `localhost` or `127.0.0.1` on a loopback bind now needs `OPENOSINT_ALLOWED_HOSTS`. A browser-based front end on another origin needs `OPENOSINT_ALLOWED_ORIGINS`.

## [2.29.0] — 2026-09-17

### Added
- `openosint/tools/search_rdap.py`: RDAP (RFC 7482/9083) domain lookup tool — the structured-JSON replacement for WHOIS used by the `openosint-domain-recon` Apify Actor. Unlike legacy WHOIS, gTLD RDAP is required by ICANN policy to redact registrant PII by default, and nothing prints a terms-of-service banner to stdout.
- `openosint/tools/search_dns.py`: `mailProfile` classification (`"no-mail"` / `"sending"` / `"unknown"`) for `analyze_email_security()`, plus the `GRADING_RUBRIC` constant documenting the full A-F rubric. A confirmed non-mail domain (RFC 7505 null MX, or no MX at all, with a strict `-all` SPF authorizing no sender — `example.com` is the canonical case) is no longer capped for "missing DKIM"; DKIM isn't required for a domain that can't send mail in the first place.
- Structured (non-text) helper functions across the OSINT tools — `run_username_osint_structured()`, `build_sherlock_site_data()`, `collect_dns_records()`, `parse_rdap_domain()` — returning machine-readable dicts/dataclasses instead of formatted strings, for Apify Actors and other callers that need structured output rather than CLI display text.

### Changed
- `openosint-username-recon` Actor: monetization switched from per-(username, platform)-hit charging (`username-found`) to per-username charging (`username-scanned`, once per username that produces at least a partial result set). Fixes unpredictable run cost — a popular username matching 100+ sites previously cost over $1 at $0.01/hit; the new model is a flat $0.04/username. The Actor now checks the remaining charge budget before starting each username and stops cleanly if the next username wouldn't fit, and reports the number of sites skipped due to timeouts per username in both the run status message and a new `SUMMARY` key-value-store record.

### Fixed
- `openosint-domain-recon` Actor: a domain with a correctly locked-down non-mail posture (null MX, `SPF -all`, `DMARC p=reject`) was previously capped at grade C for "missing DKIM," even though a domain that can't send mail has no use for DKIM.

## [2.28.2] — 2026-09-14

### Fixed
- **With `--provider openai`, gpt-4o refused to run tools that use API keys**, reporting the credentials as missing even when correctly configured. Tool descriptions said "Requires <VAR>", which the model treated as a precondition it had to verify and could not. Tools are now always called, and whatever error they return is reported.
- README: optional features install via extras, e.g. `pip install "openosint[openai]"`.

## [2.28.0] — 2026-09-13

### Changed — BREAKING
- **Web UI: locally-held provider keys are now gated by bind address, not an
  env var.** Previously, whether a request could use a key from your `.env`
  depended on `OPENOSINT_DEMO_MODE`, which defaulted to off — meaning a
  server bound to a non-loopback interface used your keys for any caller
  unless you remembered to set that variable. It's now a network-exposure
  invariant: bound to `127.0.0.1`/`localhost`, keys work as before, no
  change needed. Bound to anything else (`--host 0.0.0.0` with
  `--allow-remote`, or an undeterminable bind address) — your keys are
  never used to serve a request; callers must supply their own, and
  `search_breach` is disabled outright regardless of key source.
  `OPENOSINT_DEMO_MODE` still exists but can now only add restriction, never
  remove it. **If you were exposing the web UI on your LAN and relying on
  your own `.env` keys with no other authentication in front of it, that no
  longer works** — see the README's Web UI section.
- **Cloud API: request logs no longer contain the target you queried.**
  `cloud/main.py`'s INFO-level root logger was letting every tool module's
  free-text log line (built for CLI/MCP debugging, and including the raw
  target) through. Cloud logging is now limited to a redacted customer
  identifier, tool name, elapsed time, and outcome status.
- **Web UI: a loopback bind behind a reverse proxy is no longer silently
  trusted.** A request carrying proxy-forwarding headers
  (`X-Forwarded-For`/`-Proto`/`-Host`, `Forwarded`, `CF-Connecting-IP`) is
  now treated the same as a non-loopback bind — local keys withheld, breach
  blocked — unless the new `OPENOSINT_TRUSTED_PROXY=true` is set. This is a
  separate variable from `TRUSTED_PROXY` (rate-limit IP attribution only,
  a lower-stakes setting some self-hosters already have on) — see the
  README before setting it, including the note that doing so makes you the
  controller for anyone the proxy relays to this instance.

### Deprecated
- `OPENOSINT_MODEL` is deprecated in favor of `ANTHROPIC_MODEL`, consistent with `OPENAI_MODEL`. The old name still works and logs a one-time warning.

### Fixed
- **`.env` was ignored with a regular `pip install openosint`.** The CLI and web server looked for `.env` inside site-packages instead of the directory the command runs from. All entry points now share one loader:
  - CLI and web UI: `$OPENOSINT_ENV_FILE`, then `.env` searching upward from the current directory, then the repo root (source checkouts).
  - MCP server: `$OPENOSINT_ENV_FILE`, then the repo root, then the current directory, because MCP clients start it from an arbitrary directory.

  Real environment variables always win. `[*] Loaded .env: <path>` is printed to stderr. If `OPENOSINT_ENV_FILE` points to a missing file, OpenOSINT prints one error line and exits with code 2. Missing-key errors now say when no `.env` was found.
- **`search_dorks_live`: Bright Data failures showed a `JSONDecodeError`
  traceback instead of the actual error.** Bright Data returns HTTP 200 at
  the API level even when the fetch failed, reporting the real outcome in
  `x-brd-*` response headers. These are now read and turned into a clear
  message, e.g. `Bright Data 502 captcha: redirect location was rejected`.
  Rate-limit and CAPTCHA failures add a hint about the 15-second block.
  There is no automatic retry: Bright Data blocks a repeated identical
  query for at least 15 seconds, and cataloged errors are not billed.
- A failed dork no longer stops the scan or prints a traceback: it logs a
  warning, the remaining dorks run, and if all fail the summary lists the
  distinct error codes.
- 401/403 responses now include Bright Data's own redacted body, with a
  specific hint when the API key has expired.
- Result URLs are normalized: opaque Google `/goto?url=...` redirect
  tokens and snippet text leaking into the URL field are no longer shown
  as links. Unresolvable links render as `(unresolved)`.
- The Twitter dork is now grouped as `("{target}") (site:x.com OR
  site:twitter.com)`; the previous form let Google match either the
  quoted term or a site independently, returning unrelated results.

## [2.27.0] — 2026-08-26

### Added
- **Local graph visualization in the web UI** — a new `/graph` explorer renders
  the FollowTheMoney entity graph store (Cytoscape.js, vendored offline) with
  node color/shape by schema, solid confirmed edges, dashed `same_as` candidate
  edges labeled with their score, canonical-cluster grouping, and a node side
  panel showing every statement with full provenance. Includes a **human review
  queue** for `same_as` candidates: two entities aligned property-by-property
  with provenance, the rule-based match score (labeled as such, not a
  probability), and Accept / Reject / Skip / Undo — one pair at a time, no bulk
  actions. New read-only, localhost-only endpoints (`/api/graph/subgraph`,
  `/api/graph/entity`, `/api/graph/review/candidates`, `/api/graph/review/decide`)
  read the local SQLite store only and make no outbound network calls.

### Fixed
- **A fresh install got a broken MCP server — the `mcp` dependency is now
  pinned to `>=1.0.0,<2`.** The previous requirement (`mcp>=1.0.0`) let a
  clean install resolve mcp 2.x, whose breaking API changes (`Server.list_tools`
  and `mcp.server.fastmcp` were removed) make `openosint.mcp_server` crash on
  import. **This affects 2.26.0: a fresh `pip install openosint==2.26.0` today
  installs a non-functional MCP server.** Existing environments that already
  had mcp 1.x are unaffected. Upgrade to 2.27.0, or in an affected 2.26.0
  environment run `pip install "mcp<2"`.
- **The web UI loaded Cytoscape from a CDN, and one of those tags was already
  broken in production.** `index.html` pulled `cytoscape` and `cytoscape-fcose`
  from third-party CDNs; the `cytoscape-fcose` tag never actually worked (its
  `cose-base`/`layout-base` dependencies were never loaded, so it silently fell
  back to the built-in layout), and any CDN request leaks that the tool is
  running to a third party. Cytoscape.js is now vendored into the repo and
  served locally; the dead `cytoscape-fcose` CDN tag was removed.
- **The web UI no longer contacts any third-party CDN.** The remaining
  runtime CDN dependencies — Alpine.js (jsdelivr), Tailwind
  (`cdn.tailwindcss.com`, the browser JIT build Tailwind itself says is not
  for production), and the Inter / JetBrains Mono fonts (Google Fonts, which
  transmits the visitor's IP to Google on every page load) — are now served
  locally: Alpine.js 3.14.1 is vendored, Tailwind 3.4.17 is a prebuilt CSS
  file committed to the repo (regenerated with the standalone CLI, no Node
  toolchain required), and the fonts are self-hosted woff2 files with their
  SIL OFL 1.1 licenses recorded alongside. Loading the web UI now makes zero
  external requests.

## [2.26.0] — 2026-08-25

### Added
- **Graph module (`openosint.graph`), an additive FollowTheMoney entity
  graph** — turns scan results into FollowTheMoney (FtM) entities with
  statement-level provenance, an append-only SQLite store, non-destructive
  same_as deduplication, and a human review queue. It sits alongside the
  existing Entity Correlation Graph without changing anything about it, and
  is entirely opt-in behind two new extras. See
  [docs/graph.md](docs/graph.md) for the full guide.
  - `pip install "openosint[graph]"` (Python 3.10+) enables entity mapping,
    the append-only store, and two new MCP tools: `graph_export` (streams
    the graph as newline-delimited FtM entity JSON, with support for
    excluding whole datasets — e.g. omitting all HaveIBeenPwned-derived
    breach data) and `graph_neighbors` (traverses the graph from one entity
    out to a given depth, with per-edge provenance).
  - `pip install "openosint[graph-dedup]"` **requires Python 3.11+** — this
    is nomenklatura's own requirement, not a choice made by this project;
    `openosint` itself still supports Python 3.10+. It adds non-destructive
    same_as candidate scoring and the third new MCP tool,
    `graph_review_candidates`: nothing in this module ever auto-merges
    entities — a human must explicitly accept or reject every suggested
    match, and a rejected pair is never re-suggested.

### Fixed
- **Breach findings never actually expanded an investigation.** The internal
  parser that turns `search_breach` (HaveIBeenPwned) results into pivotable
  entities had a regex bug that meant a breach name was never recognized,
  even when breaches were found and reported to the user. This silently
  disabled breach-triggered pivoting in the auto-pivot investigation engine
  (`investigate_graph`) — an investigation that found breaches never chased
  the breach name any further. No prior test exercised this path. Past
  investigations that relied on auto-pivoting from a breached email may have
  missed connections the breach data would have revealed. Fixed.

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
