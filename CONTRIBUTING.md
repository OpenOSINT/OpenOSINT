# Contributing to OpenOSINT

Thank you for your interest in contributing. This document covers the development
workflow and the checklist for adding new integrations.

Before contributing, read [DISCLAIMER.md](DISCLAIMER.md). OpenOSINT is for
authorized security research and educational use only.

## Getting started

```bash
# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint and format
ruff check openosint/
ruff format openosint/
```

## Development workflow

1. Fork the repository and create a branch from `main`.
2. Write tests first; implementation follows. Target 80% coverage on new code.
3. Run `pytest` and `ruff check` before opening a pull request.
4. Use the pull request template — fill in the summary, type of change, and
   checklist before requesting review.

## Adding a new integration

A "tool" in OpenOSINT is a Python module in `openosint/tools/` that exposes an
`async def run_*_osint(...)` coroutine. Adding a new tool requires registering
it in every interface layer:

| Layer | File | What to do |
|-------|------|------------|
| Tool module | `openosint/tools/search_<name>.py` | Implement `run_<name>_osint` |
| Agentic loop | `openosint/agent.py` | Import the function; add a tool definition to the tools list and a dispatch branch in the tool executor |
| MCP server | `openosint/mcp_server.py` | Import the function; add an entry to the tool registry dict |
| CLI | `openosint/cli.py` | Add a subcommand (argparse) that calls the tool directly |
| REPL | `openosint/repl.py` | Add the tool to the displayed tool list and any command completion |
| Web UI | `openosint/web_server.py` | Add the tool to the tool dispatch map used by the web endpoint |

### Environment variable convention

If the integration requires an API key, follow this naming pattern:

```
<SERVICE_NAME>_API_KEY
```

Examples: `SHODAN_API_KEY`, `VIRUSTOTAL_API_KEY`, `CENSYS_API_ID`.

Add the new variable to `.env.example` with a comment explaining where to obtain
it, and document it in the environment variables table in `README.md` and
`CLAUDE.md`.

### Tests

Add at least one test for the new tool in `tests/`. The test should:

- Cover the happy path (valid input, expected output format).
- Cover the error path (missing binary, API error, timeout).
- Mock external HTTP calls or subprocesses — do not make live network requests
  in the test suite.

### Integrations table

Add a row for the new service to the Integrations table in `README.md` with the
service name, URL, tool name, and tier (`Community`).

## Regenerating the demo GIF/MP4

```bash
export OPENOSINT_DEMO_KEY=sk-ant-...   # your Anthropic key, never committed
openosint web &                        # start the web server on :8080
make demo                              # record -> encode -> write docs/assets/demo-web-graph.*
git add docs/assets/demo-web-graph.*
```

See [`scripts/record-demo/README.md`](scripts/record-demo/README.md) for prerequisites and pipeline details.

## Regenerating the plugin demo

`assets/demo/skill-demo.tape` drives a real Claude Code session with [VHS](https://github.com/charmbracelet/vhs)
(`brew install vhs`): marketplace add, plugin install, then `/openosint:osint example.com`.
It uses your normal Claude Code login, so set the machine up first and restore it after:

```bash
# 1. Fresh-install state: no openosint plugin or marketplace, noisy plugins off
claude plugin uninstall openosint@openosint
claude plugin marketplace remove openosint
claude plugin disable <each plugin that prints notices or runs hooks>

# 2. Demo folder that pre-allows the tools, so no permission prompt appears on screen
mkdir -p /tmp/openosint-demo/.claude
cat > /tmp/openosint-demo/.claude/settings.local.json <<'JSON'
{"permissions": {"allow": ["Bash(uvx --from openosint==2.38.0 openosint *)", "mcp__plugin_openosint_openosint__*"]}}
JSON

# 3. Record (one take costs a few API calls). Raw video lands in /tmp/openosint-demo-raw/
mkdir -p /tmp/openosint-demo-raw && vhs assets/demo/skill-demo.tape
```

Then post-process the raw video (needs `ffmpeg`, `gifsicle`, `tesseract` and `pip install numpy pillow`):

```bash
python assets/demo/skill-demo-post.py /tmp/openosint-demo-raw/raw.mp4 --deny you@example.com --deny yourname
```

It masks the Claude Code header that stays on screen after `/clear` (logo, version, plan), speeds
up idle "model is thinking" frames, holds the final frame for 3s, writes `skill-demo.mp4` (H.264)
and `skill-demo.gif` (under 5 MB), and OCRs every output frame. It refuses to write anything if
your email, username, home paths or keys appear, so pass your own identifiers with `--deny`.

Afterwards re-add the marketplace, reinstall `openosint@openosint` and re-enable the plugins you
disabled. Never commit `.cast` files or temp config. Keep the version in the `settings.local.json`
rule in sync with `.mcp.json`.

## Contributor License Agreement

Before your first pull request can be merged, you must sign the
[Contributor License Agreement (CLA)](./CLA.md). The CLA bot will post a comment on your
PR with instructions — reply with the text shown to sign. Signing is a one-time action per
GitHub account. It grants the maintainer a perpetual license to use your contributions,
including a relicensing right that keeps future dual-licensing options open. You retain full
ownership of your contributions.

## Reporting issues

Use the issue templates on GitHub:

- **Bug report** — unexpected behavior, crashes, or incorrect output.
- **Feature request** — new functionality or enhancements.
- **New integration** — request to add a new OSINT data source or API.

For sponsorship and partnership inquiries, email
[commercial@openosint.tech](mailto:commercial@openosint.tech?subject=OpenOSINT%20Sponsorship%20Inquiry).
