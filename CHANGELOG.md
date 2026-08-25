# Changelog

All notable changes to OpenOSINT are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
OpenOSINT adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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
