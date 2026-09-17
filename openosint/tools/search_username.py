# openosint/tools/search_username.py
"""
Username OSINT module.

Wraps the 'sherlock' binary to enumerate social networks and platforms where a
target username is registered. Returns a formatted string; never raises.
"""

from __future__ import annotations

import asyncio
import logging

from openosint.proxy import get_sherlock_proxy_args
from openosint.tools.exceptions import OSINTError, ToolExecutionError
from openosint.utils import run_subprocess

logger = logging.getLogger(__name__)

_BINARY = "sherlock"
_DEFAULT_TIMEOUT = 180  # overall subprocess timeout for the CLI-invoking run_username_osint() below
_INSTALL_HINT = "Install it with: pip install sherlock-project"
_PER_SITE_TIMEOUT = "3"  # seconds per site, passed to sherlock --timeout (CLI path)

# Per-HTTP-request timeout passed to sherlock's own sherlock() call (library path,
# run_username_osint_structured() below). This is NOT the same knob as _DEFAULT_TIMEOUT
# above — that one bounds the whole CLI subprocess, this one bounds a single site's
# HTTP request. Conflating the two previously caused every unresponsive site to be
# allowed up to 180s each, with sherlock's own internal 20-worker cap meaning a
# handful of slow sites could stall an entire scan for minutes.
_DEFAULT_SITE_REQUEST_TIMEOUT_SECONDS = 10


async def _run_sherlock(username: str, timeout_seconds: int) -> str:
    """Execute sherlock against username and return raw stdout."""
    result = await run_subprocess(
        binary=_BINARY,
        args=[username, "--print-found", "--timeout", _PER_SITE_TIMEOUT, *get_sherlock_proxy_args()],
        timeout_seconds=timeout_seconds,
        install_hint=_INSTALL_HINT,
    )
    return result.stdout


def _format_username_results(raw: str, username: str) -> str:
    """Return a structured string suitable for CLI display and LLM consumption."""
    if not raw:
        return f"No accounts found for username '{username}'."
    return f"OSINT results for username '{username}':\n\n{raw}"


async def run_username_osint(
    username: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
) -> str:
    """
    Run a username OSINT scan and return a formatted result string.

    Calls sherlock to enumerate platforms where the username is registered.
    Returns a descriptive error string on failure rather than raising.

    Parameters
    ----------
    username:
        Target username or alias.
    timeout_seconds:
        Maximum execution time for the sherlock subprocess.

    Returns
    -------
    str
        Formatted result string or a descriptive error message.
    """
    logger.info("Starting username OSINT scan for: %s", username)
    try:
        raw = await _run_sherlock(username, timeout_seconds)
        result = _format_username_results(raw, username)
        logger.info("Username scan complete for: %s", username)
        return result
    except OSINTError as exc:
        logger.warning("Username scan failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:  # pragma: no cover
        logger.exception("Unexpected error during username scan.")
        return f"Internal error: {exc}"


def build_sherlock_site_data() -> dict:
    """
    Load sherlock's site catalog (NSFW sites excluded), for structured scans.

    Call once per batch of usernames and reuse the result — this pulls the
    live site manifest and exclusion list from sherlock-project over the
    network, which is unnecessary work if you're checking more than one
    username.

    Raises
    ------
    OSINTError
        When sherlock-project is not installed as a library, or the site
        catalog cannot be loaded.
    """
    try:
        from sherlock_project.sites import SitesInformation
    except ImportError as exc:
        raise OSINTError("sherlock-project is not installed. Run: pip install sherlock-project") from exc

    try:
        sites = SitesInformation()
    except Exception as exc:
        raise OSINTError(f"Failed to load sherlock site catalog: {exc}") from exc

    sites.remove_nsfw_sites()
    return {site.name: site.information for site in sites}


def _run_sherlock_structured(username: str, site_data: dict, timeout_seconds: int) -> list[dict]:
    from sherlock_project.notify import QueryNotify
    from sherlock_project.result import QueryStatus
    from sherlock_project.sherlock import sherlock

    try:
        raw_results = sherlock(username, site_data, QueryNotify(), timeout=timeout_seconds)
    except Exception as exc:
        raise ToolExecutionError(f"sherlock scan failed for '{username}': {exc}") from exc

    found = []
    for platform, data in raw_results.items():
        status = data.get("status")
        if status is None or status.status != QueryStatus.CLAIMED:
            continue
        # sherlock's site catalog carries no per-site category taxonomy —
        # category is always None until/unless a manual mapping is added.
        found.append(
            {
                "username": username,
                "platform": platform,
                "url": status.site_url_user,
                "category": None,
            }
        )
    return found


async def run_username_osint_structured(
    username: str,
    site_data: dict,
    timeout_seconds: int = _DEFAULT_SITE_REQUEST_TIMEOUT_SECONDS,
) -> list[dict]:
    """
    Run a structured sherlock scan for username, returning one dict per hit.

    Unlike run_username_osint(), this calls sherlock's library API directly
    (no subprocess, no text parsing) and returns machine-readable rows:
    {username, platform, url, category}. Raises OSINTError/ToolExecutionError
    on failure instead of returning an error string — callers that need the
    "never raises" contract should use run_username_osint() instead.

    Parameters
    ----------
    username:
        Target username or alias.
    site_data:
        Sherlock site catalog, from build_sherlock_site_data(). Passed in so
        callers scanning multiple usernames load it once and reuse it.
    timeout_seconds:
        Per-site request timeout passed through to sherlock.
    """
    return await asyncio.to_thread(_run_sherlock_structured, username, site_data, timeout_seconds)
