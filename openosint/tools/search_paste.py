# openosint/tools/search_paste.py
"""
Pastebin dump search module.

Queries the psbdmp.ws public API to find pastes mentioning a target email
address or username. Returns a formatted string; never raises on failure.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse

import requests

from openosint.tools.exceptions import OSINTError, ToolExecutionError

logger = logging.getLogger(__name__)

_PSBDMP_URL = "https://psbdmp.ws/api/search/{query}"
_DEFAULT_TIMEOUT = 15
_MAX_RESULTS = 10


def _fetch_paste_data(query: str, timeout_seconds: int) -> list[dict]:
    """
    Query psbdmp.ws for pastes mentioning query.

    Raises
    ------
    OSINTError
        On network failures.
    ToolExecutionError
        On unexpected HTTP status codes.
    """
    try:
        response = requests.get(
            _PSBDMP_URL.format(query=urllib.parse.quote(query, safe="")),
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise OSINTError(f"Network error querying psbdmp.ws: {exc}") from exc

    if response.status_code == 404:
        return []
    if response.status_code != 200:
        raise ToolExecutionError(f"psbdmp.ws returned HTTP {response.status_code}.")

    data = response.json()
    return data.get("data", []) if isinstance(data, dict) else []


def _format_paste_results(pastes: list[dict], query: str) -> str:
    """Return a structured string describing paste search findings."""
    if not pastes:
        return f"No pastes found mentioning '{query}'."

    count = len(pastes)
    shown = pastes[:_MAX_RESULTS]
    lines = [f"Found in {count} paste(s) for '{query}':\n"]
    for paste in shown:
        paste_id = paste.get("id", "unknown")
        date = paste.get("time", "unknown date")
        lines.append(f"[+] https://pastebin.com/{paste_id} ({date})")
    if count > _MAX_RESULTS:
        lines.append(f"\n... and {count - _MAX_RESULTS} more.")
    return "\n".join(lines)


async def run_paste_osint(
    query: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
) -> str:
    """
    Search Pastebin dumps for query via psbdmp.ws.

    Returns a descriptive error string on failure rather than raising.

    Parameters
    ----------
    query:
        Email address or username to search for.
    timeout_seconds:
        HTTP request timeout in seconds.

    Returns
    -------
    str
        Formatted result string or a descriptive error message.
    """
    logger.info("Starting paste search for: %s", query)
    try:
        pastes = await asyncio.to_thread(_fetch_paste_data, query, timeout_seconds)
        result = _format_paste_results(pastes, query)
        logger.info("Paste search complete for: %s", query)
        return result
    except OSINTError as exc:
        logger.warning("Paste search failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during paste search.")
        return f"Internal error: {exc}"
