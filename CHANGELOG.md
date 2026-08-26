# Changelog

All notable changes to OpenOSINT are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
OpenOSINT adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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
- **The web UI loaded Cytoscape from a CDN, and one of those tags was already
  broken in production.** `index.html` pulled `cytoscape` and `cytoscape-fcose`
  from third-party CDNs; the `cytoscape-fcose` tag never actually worked (its
  `cose-base`/`layout-base` dependencies were never loaded, so it silently fell
  back to the built-in layout), and any CDN request leaks that the tool is
  running to a third party. Cytoscape.js is now vendored into the repo and
  served locally; the dead `cytoscape-fcose` CDN tag was removed.

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
