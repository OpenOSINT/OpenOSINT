# AGENTS.md — OpenOSINT developer instructions for OpenCode sessions

## Project setup

- Python 3.10+ package `openosint==2.20.0`, setuptools backend (`pyproject.toml`).
- **`uv.lock` exists.** Prefer `uv` commands:
  - `uv pip install -e ".[dev,web]"`
  - `uv run pytest`
- Two entrypoints (`[project.scripts]`):
  - `openosint` → `openosint.cli:main` (interactive REPL or direct CLI subcommands)
  - `openosint-mcp` → `openosint.mcp_server:main` (MCP stdio server)
- `openosint web` is a CLI **subcommand** dispatched from `cli.py` (line ~957), not a separate `[project.scripts]` entry. Starts FastAPI + SSE, opens browser.

## Architecture (flat, no DB, no ORM)

- **18 tool modules** under `openosint/tools/`. Every tool follows:
  ```python
  async def run_<name>_osint(...) -> str  # never raises, catches errors, returns human-readable string
  ```
- Agent loop in `openosint/agent.py`. Three provider classes (`OpenOSINTAgent`, `OllamaAgent`, `OpenAICompatibleAgent`) share a `_TOOL_MAP` of lambda dispatchers (dict mapping tool names → coroutines).
- `_TOOL_MAP` maps each string name to a lambda that destructures the input dict and calls the coroutine. `_execute_tool()` looks up the name and awaits.
- **Tool definitions live in `TOOL_DEFINITIONS` list** (Anthropic input_schema format) just above `_TOOL_MAP` (~300 lines of schema definitions, starting around line 59 in `agent.py`). Both must be kept in sync.
- **Exception:** `generate_dorks.py` exposes `run_dork_osint()` instead of `run_generate_dorks_osint()` — an existing naming inconsistency.

## Adding a new tool — 6 files

From `CONTRIBUTING.md`: every new integration requires updates in **all** of:
1. `openosint/tools/search_<name>.py` — implement `run_<name>_osint`
2. `openosint/agent.py` — import + `TOOL_DEFINITIONS` entry + `_TOOL_MAP` branch
3. `openosint/mcp_server.py` — import + tool registry entry
4. `openosint/cli.py` — import + subcommand parser + dispatch
5. `openosint/repl.py` — tool info row + completion list
6. `openosint/web_server.py` — import + `_TOOL_CATALOG` entry + `_RUNNERS` dispatch lambda

**Agents often miss #2 (the `_TOOL_MAP` lambda) or #6 (the `_RUNNERS` map).**

### Notable gaps in web_server.py

`web_server.py` does **not** include `search_abuseipdb`, `search_dns`, or `search_github` in its `_TOOL_CATALOG` or `_RUNNERS` dict. If adding those to the web layer, they must be added from scratch.

## External binaries on PATH

| Binary | Tool |
|--------|------|
| `holehe` | `search_email` |
| `sherlock` | `search_username` |
| `sublist3r` | `search_domain` |
| `phoneinfoga` | `search_phone` |

App handles missing binaries gracefully (returns error string), but tools will not produce results without them.

## ENV config

- `python-dotenv` loads `.env` at startup (`openosint/cli.py`). 16 vars in `.env.example`. **Never hardcode keys.**
- API keys follow pattern: `<SERVICE>_API_KEY` (e.g. `SHODAN_API_KEY`, `VIRUSTOTAL_API_KEY`, `ABUSEIPDB_API_KEY`). Exceptions: `CENSYS_API_ID`/`CENSYS_SECRET`, `GITHUB_TOKEN`, `IPINFO_TOKEN`, and Bright Data zone names (`BRIGHTDATA_SERP_ZONE`, `BRIGHTDATA_UNLOCKER_ZONE`).

## Gotchas

- **Two copies of exceptions module:**
  - `openosint/exceptions.py` — **dead / unused.** Do not import.
  - `openosint/tools/exceptions.py` — **the real one,** used by all tool modules and `utils.py`.
- **Stale version in web_server.py:** `openosint/__init__.py` has `__version__ = "2.20.0"` (uses `__version__`) but `openosint/web_server.py` has `_VERSION = "2.18.1"` (uses `_VERSION`) on line 58. Note the different variable names — update both when bumping.
- **`LlamaCppTransport`** in `openosint/llama_transport.py`: workaround for llama.cpp HTTP 400 incompatibility with httpx/httpcore. Active only with `--openai-raw-socket`.
- `sponsors.json` at repo root is validated at runtime. Do not break its schema.
- **`run_subprocess` utility in `openosint/utils.py`:** Reusable asyncio subprocess wrapper with PATH resolution (including venv bin), timeout, and kill. Used by all 4 binary-dependent tools. Reuse this when adding new binary tools.

## Lint / test / check

```bash
ruff check openosint/          # py310 target, line-length 100, E501 ignored
ruff format openosint/
pytest                         # asyncio_mode = auto, fixture loop_scope = function
```

- **Order matters:** `ruff check` → `pytest`. No CI workflows exist — no typecheck gate enforced.
- Mypy: `ignore_missing_imports = true`; `openosint.web_server` errors are fully ignored.

## Output files

- Reports auto-saved as Markdown (and optional PDF) to `./reports/`.
- Session history to `~/.openosint/history/`.
- **Two session-history stores:** `~/.openosint/history/` (structured session records from `session_history.py`) and `~/.openosint_history` (flat file used by prompt_toolkit for CLI input recall only).
- Docker + docker-compose available for quick deployment.
