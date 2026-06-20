# openosint/tools/search_breach.py
"""
Data breach module.

Queries the HaveIBeenPwned v3 API to check whether an email address appears
in known public data breaches. Requires HIBP_API_KEY environment variable.
Returns a formatted string; never raises on failure.
"""

from __future__ import annotations

import asyncio
import logging
import os
import urllib.parse

import requests

from openosint.cache import cached
from openosint.tools.exceptions import OSINTError, ToolExecutionError

logger = logging.getLogger(__name__)

_HIBP_API_URL = "https://haveibeenpwned.com/api/v3/breachedaccount/{email}"
_DEFAULT_TIMEOUT = 15
_USER_AGENT = "OpenOSINT/2.8.0"


def _fetch_hibp_breaches(email: str, timeout_seconds: int) -> list[dict]:
    """
    Query the HIBP v3 API for breaches associated with email.

    Raises
    ------
    OSINTError
        On missing API key, HTTP errors, or network failures.
    """
    api_key = os.environ.get("HIBP_API_KEY", "")
    if not api_key:
        raise OSINTError(
            "HIBP_API_KEY environment variable is not set. "
            "Get a key at https://haveibeenpwned.com/API/Key"
        )

    headers = {"hibp-api-key": api_key, "user-agent": _USER_AGENT}
    url = _HIBP_API_URL.format(email=urllib.parse.quote(email, safe="@/"))

    try:
        response = requests.get(
            url,
            headers=headers,
            params={"truncateResponse": "false"},
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise OSINTError(f"Network error querying HIBP: {exc}") from exc

    if response.status_code == 404:
        return []
    if response.status_code == 401:
        raise OSINTError("Invalid HIBP API key.")
    if response.status_code == 429:
        raise OSINTError("HIBP rate limit exceeded. Wait 1 second and retry.")
    if response.status_code != 200:
        raise ToolExecutionError(f"HIBP returned HTTP {response.status_code}.")

    return response.json()


def _format_breach_results(breaches: list[dict], email: str) -> str:
    """Return a structured string describing breach findings."""
    if not breaches:
        return f"No breaches found for '{email}'."

    lines = [f"Found in {len(breaches)} breach(es) for '{email}':\n"]
    for breach in breaches:
        data_classes = ", ".join(breach.get("DataClasses", [])[:4])
        lines.append(
            f"[+] {breach['Name']} ({breach.get('BreachDate', 'unknown')}) — leaked: {data_classes}"
        )
    return "\n".join(lines)


@cached(ttl=600)
async def run_breach_osint(
    email: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
) -> str:
    """
    Check whether email appears in known data breaches via HIBP.

    Requires HIBP_API_KEY environment variable. Returns a descriptive error
    string on failure rather than raising.

    Parameters
    ----------
    email:
        Target email address.
    timeout_seconds:
        HTTP request timeout in seconds.

    Returns
    -------
    str
        Formatted result string or a descriptive error message.
    """
    logger.info("Starting breach check for: %s", email)
    try:
        breaches = await asyncio.to_thread(_fetch_hibp_breaches, email, timeout_seconds)
        result = _format_breach_results(breaches, email)
        logger.info("Breach check complete for: %s", email)
        return result
    except OSINTError as exc:
        logger.warning("Breach check failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during breach check.")
        return f"Internal error: {exc}"
