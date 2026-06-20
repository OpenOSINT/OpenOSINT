# openosint/tools/search_shodan.py
"""
Shodan integration module.

Queries the Shodan API for host intelligence (IP lookup)
or general keyword/banner searches.

Requires SHODAN_API_KEY environment variable.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from openosint.cache import cached
from openosint.tools.exceptions import OSINTError

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30
_IP_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_ip_address(query: str) -> bool:
    """Return True when query looks like an IPv4 address."""
    return bool(_IP_RE.match(query.strip()))


def _format_host(data: dict, ip: str) -> str:
    lines = [f"Shodan host intelligence for '{ip}':\n"]
    if data.get("ip_str"):
        lines.append(f"[+] IP: {data['ip_str']}")
    if data.get("org"):
        lines.append(f"[+] Org: {data['org']}")
    if data.get("country_name"):
        lines.append(f"[+] Country: {data['country_name']}")
    if data.get("city"):
        lines.append(f"[+] City: {data['city']}")
    if data.get("os"):
        lines.append(f"[+] OS: {data['os']}")
    if data.get("hostnames"):
        lines.append(f"[+] Hostnames: {', '.join(data['hostnames'][:5])}")
    ports = [str(s.get("port")) for s in data.get("data", []) if s.get("port")]
    if ports:
        lines.append(f"[+] Open ports: {', '.join(ports[:20])}")
    vulns = list(data.get("vulns", {}).keys())
    if vulns:
        lines.append(f"[+] Vulnerabilities: {', '.join(vulns[:10])}")
    if len(lines) == 1:
        lines.append(f"[+] No additional details available for {ip}.")
    return "\n".join(lines)


def _format_search(results: dict, query: str) -> str:
    total = results.get("total", 0)
    matches = results.get("matches", [])
    if not matches:
        return f"No Shodan results found for '{query}'."
    lines = [f"Shodan search results for '{query}' ({total} total, showing {len(matches)}):\n"]
    for m in matches:
        ip = m.get("ip_str", "unknown")
        port = m.get("port", "?")
        org = m.get("org", "unknown")
        country = m.get("location", {}).get("country_name", "unknown")
        lines.append(f"[+] {ip}:{port} — {org} — {country}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@cached(ttl=300)
async def run_shodan_osint(query: str, timeout_seconds: int = _DEFAULT_TIMEOUT) -> str:
    """
    Run a Shodan lookup for *query*.

    If *query* looks like an IPv4 address, performs a host lookup via
    ``api.host()``.  Otherwise performs a keyword search via
    ``api.search(limit=10)``.

    Requires ``SHODAN_API_KEY`` environment variable.

    Returns
    -------
    str
        Formatted result string or descriptive error message.
    """
    api_key = os.environ.get("SHODAN_API_KEY", "")
    if not api_key:
        return (
            "Scan error: SHODAN_API_KEY environment variable is not set. "
            "Get a free key at https://account.shodan.io"
        )

    try:
        import shodan  # type: ignore
    except ImportError:
        return "Scan error: 'shodan' library is not installed. Install it with: pip install shodan"

    logger.info("Starting Shodan lookup for: %s", query)
    try:
        api = shodan.Shodan(api_key)
        if _is_ip_address(query):
            data = await asyncio.wait_for(
                asyncio.to_thread(api.host, query),
                timeout=float(timeout_seconds),
            )
            result = _format_host(data, query)
        else:
            results = await asyncio.wait_for(
                asyncio.to_thread(api.search, query, limit=10),
                timeout=float(timeout_seconds),
            )
            result = _format_search(results, query)
        logger.info("Shodan lookup complete for: %s", query)
        return result

    except asyncio.TimeoutError:
        return f"Scan error: Shodan request timed out after {timeout_seconds}s."
    except shodan.APIError as exc:  # type: ignore
        logger.warning("Shodan API error: %s", exc)
        return f"Scan error: Shodan API error: {exc}"
    except OSINTError as exc:
        logger.warning("Shodan scan failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during Shodan lookup.")
        return f"Internal error: {exc}"
