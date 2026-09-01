# openosint/tools/search_abuseipdb.py
"""
AbuseIPDB integration module.

Checks an IP address against the AbuseIPDB v2 API for abuse reputation.
Returns abuse confidence score, total reports, country, ISP, domain,
and last reported timestamp. Requires ABUSEIPDB_API_KEY.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

import aiohttp

from openosint.proxy import get_aiohttp_connector, get_aiohttp_proxy
from openosint.utils import get_ssl_context

logger = logging.getLogger(__name__)

_API_URL = "https://api.abuseipdb.com/api/v2/check"
_DEFAULT_TIMEOUT = 30
_MAX_AGE_IN_DAYS = 90
ABUSE_SCORE_THRESHOLD = 50

_MISSING_KEY_ERROR = (
    "Scan error: ABUSEIPDB_API_KEY environment variable is not set. "
    "Get a key at https://www.abuseipdb.com/account/api"
)

_IP_RE = re.compile(
    r"^("
    r"(\d{1,3}\.){3}\d{1,3}"  # IPv4
    r"|"
    r"([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}"  # IPv6 (simplified)
    r")$"
)


def _is_valid_ip(ip: str) -> bool:
    return bool(_IP_RE.match(ip.strip()))


def _raise_for_status(status: int) -> None:
    if status == 401:
        raise ValueError("AbuseIPDB: invalid API key.")
    if status == 422:
        raise ValueError("AbuseIPDB: invalid IP address or request.")
    if status == 429:
        raise ValueError("AbuseIPDB: rate limit exceeded.")
    if status != 200:
        raise ValueError(f"AbuseIPDB returned HTTP {status}.")


async def _fetch_abuseipdb_data(ip: str, api_key: str, timeout: int) -> dict:
    headers = {"Key": api_key, "Accept": "application/json"}
    params = {"ipAddress": ip, "maxAgeInDays": str(_MAX_AGE_IN_DAYS)}
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(
        timeout=timeout_cfg, connector=get_aiohttp_connector()
    ) as session:
        async with session.get(
            _API_URL,
            headers=headers,
            params=params,
            proxy=get_aiohttp_proxy(),
            ssl=get_ssl_context(),
        ) as resp:
            _raise_for_status(resp.status)
            return await resp.json()


def _format_results(data: dict) -> str:
    score = data.get("abuseConfidenceScore", 0)
    lines = [
        f"[AbuseIPDB] IP: {data.get('ipAddress', '')}",
        f"[AbuseIPDB] Abuse Confidence Score: {score}%",
        f"[AbuseIPDB] Total Reports: {data.get('totalReports', 0)}",
        f"[AbuseIPDB] Country: {data.get('countryCode', 'N/A')}",
        f"[AbuseIPDB] ISP: {data.get('isp', 'N/A')}",
        f"[AbuseIPDB] Domain: {data.get('domain', 'N/A')}",
        f"[AbuseIPDB] Last Reported: {data.get('lastReportedAt') or 'Never'}",
    ]
    if score > ABUSE_SCORE_THRESHOLD:
        lines.append("⚠️  HIGH ABUSE CONFIDENCE — flagged by AbuseIPDB")
    return "\n".join(lines)


async def run_abuseipdb_osint(ip: str, timeout_seconds: int = _DEFAULT_TIMEOUT, *, api_key: str | None = None) -> str:
    """Check an IP against the AbuseIPDB v2 API. Requires ABUSEIPDB_API_KEY."""
    resolved_key = api_key or os.environ.get("ABUSEIPDB_API_KEY", "")
    if not resolved_key:
        return _MISSING_KEY_ERROR
    ip = ip.strip()
    if not _is_valid_ip(ip):
        return "Invalid IP address format."
    try:
        payload = await _fetch_abuseipdb_data(ip, resolved_key, timeout_seconds)
        return _format_results(payload.get("data", {}))
    except asyncio.TimeoutError:
        return f"Scan error: AbuseIPDB request timed out after {timeout_seconds}s."
    except aiohttp.ClientError as exc:
        return f"Scan error: Network error querying AbuseIPDB: {exc}"
    except ValueError as exc:
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during AbuseIPDB lookup.")
        return f"Internal error: {exc}"
