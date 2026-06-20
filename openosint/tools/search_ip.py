# openosint/tools/search_ip.py
"""
IP intelligence module.

Queries ipinfo.io to retrieve geolocation, ASN, hostname, and organisation
data for a target IP address. Free tier: 50k requests/month, no key required.
Set IPINFO_TOKEN env var for higher limits. Returns a formatted string; never raises.
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

_IPINFO_URL = "https://ipinfo.io/{ip}/json"
_DEFAULT_TIMEOUT = 10


def _fetch_ip_data(ip: str, timeout_seconds: int) -> dict:
    """
    Query ipinfo.io for geolocation and ASN data for ip.

    Raises
    ------
    OSINTError
        On rate limiting or network failures.
    ToolExecutionError
        On unexpected HTTP status codes.
    """
    token = os.environ.get("IPINFO_TOKEN", "")
    params: dict = {"token": token} if token else {}

    try:
        response = requests.get(
            _IPINFO_URL.format(ip=urllib.parse.quote(ip, safe="")),
            params=params,
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise OSINTError(f"Network error querying ipinfo.io: {exc}") from exc

    if response.status_code == 429:
        raise OSINTError(
            "ipinfo.io rate limit exceeded. "
            "Set IPINFO_TOKEN for higher limits: https://ipinfo.io/signup"
        )
    if response.status_code != 200:
        raise ToolExecutionError(f"ipinfo.io returned HTTP {response.status_code}.")

    return response.json()


def _format_ip_results(data: dict, ip: str) -> str:
    """Return a structured string describing IP intelligence."""
    if "bogon" in data:
        return f"'{ip}' is a bogon/private address — no public data available."

    fields = ["ip", "hostname", "org", "city", "region", "country", "loc", "timezone"]
    lines = [f"IP intelligence for '{ip}':\n"]
    for field in fields:
        value = data.get(field)
        if value:
            lines.append(f"[+] {field.capitalize()}: {value}")
    return "\n".join(lines)


@cached(ttl=600)
async def run_ip_osint(
    ip: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
) -> str:
    """
    Retrieve geolocation and ASN data for ip via ipinfo.io.

    Returns a descriptive error string on failure rather than raising.

    Parameters
    ----------
    ip:
        Target IPv4 or IPv6 address.
    timeout_seconds:
        HTTP request timeout in seconds.

    Returns
    -------
    str
        Formatted result string or a descriptive error message.
    """
    logger.info("Starting IP lookup for: %s", ip)
    try:
        data = await asyncio.to_thread(_fetch_ip_data, ip, timeout_seconds)
        result = _format_ip_results(data, ip)
        logger.info("IP lookup complete for: %s", ip)
        return result
    except OSINTError as exc:
        logger.warning("IP lookup failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during IP lookup.")
        return f"Internal error: {exc}"
