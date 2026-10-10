"""
OpenOSINT Cloud — tool dispatch for the gateway.

ALLOW_LIST is the single source of truth for the v1 synchronous tool set.
Scope: infrastructure and host/cert intelligence. No personal-data lookups,
no breach/leak sources (e.g. search_breach / HaveIBeenPwned is deliberately
excluded — see tests/test_cloud.py's allow-list guard test).

Every tool here must complete under the Heroku 30 s HTTP router limit
(TOOL_TIMEOUT_SECONDS = 25 s with headroom).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

from cloud.config import TOOL_TIMEOUT_SECONDS
from openosint.json_output import format_tool_result
from openosint.tool_policy import disabled_result, humanize, is_tool_enabled
from openosint.tools.search_abuseipdb import run_abuseipdb_osint
from openosint.tools.search_censys import run_censys_osint
from openosint.tools.search_dns import run_dns_osint
from openosint.tools.search_domain import run_domain_osint
from openosint.tools.search_ip import run_ip_osint
from openosint.tools.search_ip2location import run_ip2location_osint
from openosint.tools.search_shodan import run_shodan_osint
from openosint.tools.search_virustotal import run_virustotal_osint

logger = logging.getLogger(__name__)


def _censys_keys(combined: str | None) -> dict[str, str] | None:
    """Split the tenant's stored 'api_id:api_secret' string for run_censys_osint."""
    if not combined:
        return None
    api_id, _, api_secret = combined.partition(":")
    return {"CENSYS_API_ID": api_id, "CENSYS_SECRET": api_secret}


# ponytail: kept out of ALLOW_LIST until SHODAN_API_KEY is set in prod (no key
# = every call fails upstream for every customer). Re-enable by adding
# "search_shodan": _SHODAN_ENTRY, back to ALLOW_LIST below — nothing else to change.
_SHODAN_ENTRY = lambda t, k: run_shodan_osint(query=t, timeout_seconds=TOOL_TIMEOUT_SECONDS, api_key=k)

# Each value is a coroutine factory: (target: str, api_key: str | None) → Awaitable[str].
ALLOW_LIST: dict[str, Callable[[str, str | None], Coroutine[Any, Any, str]]] = {
    "search_ip":          lambda t, k: run_ip_osint(ip=t, timeout_seconds=TOOL_TIMEOUT_SECONDS, api_key=k),
    "search_ip2location": lambda t, k: run_ip2location_osint(ip=t, timeout_seconds=TOOL_TIMEOUT_SECONDS, api_key=k),
    "search_abuseipdb":   lambda t, k: run_abuseipdb_osint(ip=t, timeout_seconds=TOOL_TIMEOUT_SECONDS, api_key=k),
    "search_dns":         lambda t, _: run_dns_osint(domain=t, timeout_seconds=TOOL_TIMEOUT_SECONDS),
    "search_domain":      lambda t, _: run_domain_osint(domain=t, timeout_seconds=TOOL_TIMEOUT_SECONDS),
    "search_virustotal":  lambda t, k: run_virustotal_osint(target=t, timeout_seconds=TOOL_TIMEOUT_SECONDS, api_key=k),
    "search_censys":      lambda t, k: run_censys_osint(t, TOOL_TIMEOUT_SECONDS, api_keys=_censys_keys(k)),
}


# Attribution required by upstream ToS on every Cloud response for this tool.
# Cloud-only: appended in dispatch() below, not in the shared
# openosint.json_output.format_tool_result() used by the CLI and MCP-local.
ATTRIBUTION: dict[str, str] = {
    "search_shodan": "Data provided by Shodan (shodan.io).",
}


async def dispatch(tool: str, target: str, api_key: str | None = None) -> dict:
    """
    Run a tool from the allow-list and return a format_tool_result dict.

    Raises ValueError if tool is not in ALLOW_LIST.
    The caller is responsible for wrapping this in asyncio.wait_for.
    """
    if tool not in ALLOW_LIST:
        raise ValueError(f"Tool '{tool}' is not available in v1")
    # Passive by default, like every other surface. A disabled tool (or a disabled mode of
    # an enabled one, e.g. a VirusTotal URL) comes back as a "Scan error:" so it is not charged.
    raw = disabled_result(tool) if not is_tool_enabled(tool) else await ALLOW_LIST[tool](target, api_key)
    if raw.startswith('{"status": "disabled_in_passive_mode"'):
        raw = f"Scan error: {humanize(raw)}"
    result = format_tool_result(tool, target, raw)
    attribution = ATTRIBUTION.get(tool)
    if attribution:
        result["results"].append(attribution)
    return result
