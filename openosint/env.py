# openosint/env.py
"""
Single .env loader shared by every entry point (CLI, web server, MCP server).

With a regular (non-editable) `pip install openosint`, the package lives
under site-packages — anchoring purely on `__file__` resolves into
`site-packages/.env`, a path no user will ever populate. A bare
`load_dotenv()` call has the same problem for the common case, since
python-dotenv's default search starts from the caller's `__file__`, not
the cwd.

Resolution order (first match wins), `override=False` throughout — a real
environment variable always beats anything in the file:
  1. `$OPENOSINT_ENV_FILE`, if set — fail loudly on a bad path rather than
     silently loading nothing.
  2. For the CLI and web server (`prefer_package_root=False`, the default):
     a `.env` found by searching upward from the current working directory
     (python-dotenv's own `usecwd=True` search) — the common case for a
     `pip install`ed `openosint` run from wherever the user's `.env` lives —
     then the repo-root `.env` next to this package as a last resort, for a
     source/editable checkout.
     For the MCP server (`prefer_package_root=True`): the same two checks
     in the OPPOSITE order — repo-root first, cwd search last. Claude
     Desktop and other MCP hosts launch this entry point with an arbitrary
     cwd (often the user's home directory or wherever the host process
     itself runs from), so an upward cwd search can pick up an unrelated
     `.env` before the repo-root one; for MCP, `OPENOSINT_ENV_FILE` (or the
     client's own `env` block) is the reliable way to point at a specific
     file — see the README.

`[*] Loaded .env: <path>` is always printed to stderr, never stdout, in
every entry point — stdout must stay clean for the MCP protocol and for
`--json` CLI output.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

_loaded_path: str | None = None
_load_attempted = False


def _resolve_path(*, prefer_package_root: bool = False) -> str:
    explicit = os.environ.get("OPENOSINT_ENV_FILE", "").strip()
    if explicit:
        if not Path(explicit).is_file():
            raise FileNotFoundError(f"OPENOSINT_ENV_FILE={explicit!r} does not exist.")
        return explicit

    repo_root_env = Path(__file__).resolve().parent.parent / ".env"

    if prefer_package_root:
        if repo_root_env.is_file():
            return str(repo_root_env)
        return find_dotenv(usecwd=True)

    cwd_env = find_dotenv(usecwd=True)
    if cwd_env:
        return cwd_env
    if repo_root_env.is_file():
        return str(repo_root_env)
    return ""


def load_env(*, prefer_package_root: bool = False) -> Path | None:
    """Load `.env` once per process and return the path loaded, or None.

    Safe to call from multiple entry points/functions — every call after
    the first is a no-op that returns the cached result, so the banner
    line below is never printed twice for one process. `prefer_package_root`
    swaps the cwd-search/repo-root priority — see the module docstring.

    Raises FileNotFoundError if `$OPENOSINT_ENV_FILE` is set but points at
    a nonexistent path — see `load_env_or_exit()` for the CLI-friendly
    wrapper every entry point should call instead of this directly.
    """
    global _loaded_path, _load_attempted
    if _load_attempted:
        return Path(_loaded_path) if _loaded_path else None

    path = _resolve_path(prefer_package_root=prefer_package_root)
    if path:
        load_dotenv(dotenv_path=path, override=False)
        print(f"[*] Loaded .env: {path}", file=sys.stderr)

    _loaded_path = path or None
    _load_attempted = True
    return Path(_loaded_path) if _loaded_path else None


def load_env_or_exit(*, prefer_package_root: bool = False) -> Path | None:
    """`load_env()`, but a bad `$OPENOSINT_ENV_FILE` exits cleanly instead of
    raising.  Every entry point (CLI, MCP server, web server) should call
    this instead of `load_env()` directly, so a missing env file always
    produces one `[!] ...` line on stderr and `exit(2)` — never a traceback.
    """
    try:
        return load_env(prefer_package_root=prefer_package_root)
    except FileNotFoundError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        raise SystemExit(2) from None


def missing_var_clause(var_name: str) -> str:
    """ "<var> environment variable is not set (...)." with no "Scan error:" prefix.

    For a tool that raises/returns its own message and lets a caller add
    that prefix when wrapping the error (see search_breach.py) — use
    missing_var_message() instead when returning the error directly.
    """
    if _load_attempted:
        # load_env() already ran (every entry point calls it before
        # importing tool modules) — report what it actually found, so this
        # matches the MCP server's swapped cwd/repo-root priority instead
        # of silently recomputing with the CLI/web default order.
        path = _loaded_path or ""
    else:
        try:
            path = _resolve_path()
        except FileNotFoundError:
            path = ""

    if path:
        hint = f".env loaded from {path}, but it doesn't set this variable"
    else:
        hint = f"no .env found in {os.getcwd()}; set OPENOSINT_ENV_FILE or export the variable"
    return f"{var_name} environment variable is not set ({hint})."


def missing_var_message(var_name: str) -> str:
    """Standard "Scan error: <var> is not set (...)" sentence for a missing key.

    Used by every OSINT tool that requires a credential, so the hint about
    where .env was (or wasn't) found is consistent everywhere instead of
    being retyped per tool.
    """
    return f"Scan error: {missing_var_clause(var_name)}"
