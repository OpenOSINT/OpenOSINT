# openosint/tools/search_virustotal.py
"""
VirusTotal integration module.

Checks IP addresses, domains, URLs, and file hashes against
VirusTotal's 70+ antivirus engines and threat intelligence.

Auto-detects the input type and calls the appropriate VirusTotal API v3
endpoint:
  - IPv4 address  → GET /ip_addresses/{ip}
  - Domain        → GET /domains/{domain}
  - URL           → POST /urls → poll GET /analyses/{id}
  - File hash     → GET /files/{hash}  (MD5 / SHA-1 / SHA-256)

Requires VIRUSTOTAL_API_KEY environment variable.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

import requests

from openosint.cache import cached
from openosint.tools.exceptions import OSINTError, ToolExecutionError

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.virustotal.com/api/v3"
_DEFAULT_TIMEOUT = 30
_POLL_ATTEMPTS = 3
_POLL_DELAY = 5  # seconds between URL analysis polls

_IP_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
_HASH_RE = re.compile(r"^([0-9a-fA-F]{32}|[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


# ---------------------------------------------------------------------------
# Input-type detection
# ---------------------------------------------------------------------------


def _detect_input_type(target: str) -> str:
    """Classify target as 'ip', 'hash', 'url', or 'domain' for API routing."""
    if _IP_RE.match(target):
        return "ip"
    if _HASH_RE.match(target):
        return "hash"
    if target.startswith("http://") or target.startswith("https://"):
        return "url"
    return "domain"


# ---------------------------------------------------------------------------
# Shared HTTP helpers
# ---------------------------------------------------------------------------


def _headers(api_key: str) -> dict[str, str]:
    return {"x-apikey": api_key, "Accept": "application/json"}


def _validate_response(response: requests.Response) -> None:
    """Raise a descriptive error for any non-success HTTP status."""
    if response.status_code == 401:
        raise OSINTError("Invalid VirusTotal API key.")
    if response.status_code == 429:
        raise OSINTError("VirusTotal rate limit reached. Try again in 60s.")
    if response.status_code == 404:
        raise OSINTError("Target not found in VirusTotal database.")
    if response.status_code not in (200, 201):
        raise ToolExecutionError(f"VirusTotal returned HTTP {response.status_code}.")


def _extract_stats(attrs: dict) -> dict[str, int]:
    raw = attrs.get("last_analysis_stats", {})
    return {
        "malicious": raw.get("malicious", 0),
        "suspicious": raw.get("suspicious", 0),
        "harmless": raw.get("harmless", 0),
        "undetected": raw.get("undetected", 0),
    }


def _append_stats(lines: list[str], stats: dict[str, int]) -> None:
    lines.append(f"[VirusTotal] Malicious: {stats['malicious']}")
    lines.append(f"[VirusTotal] Suspicious: {stats['suspicious']}")
    lines.append(f"[VirusTotal] Harmless: {stats['harmless']}")
    lines.append(f"[VirusTotal] Undetected: {stats['undetected']}")
    if stats["malicious"] > 0:
        lines.append(f"⚠️  FLAGGED AS MALICIOUS by {stats['malicious']} engines")


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def _format_ip(data: dict) -> str:
    attrs = data.get("data", {}).get("attributes", {})
    lines = ["[VirusTotal] Type: ip"]
    country = attrs.get("country", "")
    if country:
        lines.append(f"[VirusTotal] Country: {country}")
    asn = attrs.get("asn", "")
    as_owner = attrs.get("as_owner", "")
    if asn:
        lines.append(f"[VirusTotal] ASN: AS{asn} {as_owner}".rstrip())
    network = attrs.get("network", "")
    if network:
        lines.append(f"[VirusTotal] Network: {network}")
    _append_stats(lines, _extract_stats(attrs))
    return "\n".join(lines)


def _format_domain(data: dict) -> str:
    attrs = data.get("data", {}).get("attributes", {})
    lines = ["[VirusTotal] Type: domain"]
    registrar = attrs.get("registrar", "")
    if registrar:
        lines.append(f"[VirusTotal] Registrar: {registrar}")
    creation = attrs.get("creation_date", "")
    if creation:
        lines.append(f"[VirusTotal] Created: {creation}")
    categories = attrs.get("categories", {})
    if categories:
        cat_vals = list(categories.values())[:3]
        lines.append(f"[VirusTotal] Categories: {', '.join(cat_vals)}")
    _append_stats(lines, _extract_stats(attrs))
    return "\n".join(lines)


def _format_url_analysis(data: dict, target_url: str) -> str:
    """Format a GET /analyses/{id} response for a URL scan."""
    attrs = data.get("data", {}).get("attributes", {})
    lines = ["[VirusTotal] Type: url"]
    lines.append(f"[VirusTotal] Final URL: {target_url}")
    # The analysis endpoint uses "stats"; fall back to "last_analysis_stats"
    raw = attrs.get("stats", attrs.get("last_analysis_stats", {}))
    stats = {
        "malicious": raw.get("malicious", 0),
        "suspicious": raw.get("suspicious", 0),
        "harmless": raw.get("harmless", 0),
        "undetected": raw.get("undetected", 0),
    }
    _append_stats(lines, stats)
    return "\n".join(lines)


def _format_hash(data: dict) -> str:
    attrs = data.get("data", {}).get("attributes", {})
    lines = ["[VirusTotal] Type: file"]
    name = attrs.get("meaningful_name", "")
    if name:
        lines.append(f"[VirusTotal] Name: {name}")
    ftype = attrs.get("type_description", "")
    if ftype:
        lines.append(f"[VirusTotal] File Type: {ftype}")
    size = attrs.get("size", "")
    if size:
        lines.append(f"[VirusTotal] Size: {size} bytes")
    threat_label = attrs.get("popular_threat_classification", {}).get("suggested_threat_label", "")
    if threat_label:
        lines.append(f"[VirusTotal] Threat Label: {threat_label}")
    _append_stats(lines, _extract_stats(attrs))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# API calls (synchronous — matches existing tool pattern)
# ---------------------------------------------------------------------------


def _lookup_ip(api_key: str, ip: str, timeout: int) -> str:
    try:
        response = requests.get(
            f"{_BASE_URL}/ip_addresses/{ip}",
            headers=_headers(api_key),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise OSINTError(f"Network error querying VirusTotal: {exc}") from exc
    _validate_response(response)
    return _format_ip(response.json())


def _lookup_domain(api_key: str, domain: str, timeout: int) -> str:
    try:
        response = requests.get(
            f"{_BASE_URL}/domains/{domain}",
            headers=_headers(api_key),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise OSINTError(f"Network error querying VirusTotal: {exc}") from exc
    _validate_response(response)
    return _format_domain(response.json())


async def _lookup_url(api_key: str, target_url: str, timeout: int) -> str:
    # Step 1 — submit URL for analysis
    try:
        submit_response = await asyncio.to_thread(
            requests.post,
            f"{_BASE_URL}/urls",
            headers=_headers(api_key),
            data={"url": target_url},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise OSINTError(f"Network error submitting URL to VirusTotal: {exc}") from exc
    _validate_response(submit_response)

    analysis_id = submit_response.json().get("data", {}).get("id", "")
    if not analysis_id:
        raise OSINTError("VirusTotal did not return an analysis ID for the URL.")

    # Step 2 — poll the analysis endpoint (max 3 attempts, 5 s apart)
    poll_data: dict = {}
    for _ in range(_POLL_ATTEMPTS):
        await asyncio.sleep(_POLL_DELAY)
        try:
            poll_response = await asyncio.to_thread(
                requests.get,
                f"{_BASE_URL}/analyses/{analysis_id}",
                headers=_headers(api_key),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise OSINTError(f"Network error polling VirusTotal analysis: {exc}") from exc
        _validate_response(poll_response)
        poll_data = poll_response.json()
        status = poll_data.get("data", {}).get("attributes", {}).get("status", "")
        if status == "completed":
            break

    return _format_url_analysis(poll_data, target_url)


def _lookup_hash(api_key: str, file_hash: str, timeout: int) -> str:
    try:
        response = requests.get(
            f"{_BASE_URL}/files/{file_hash}",
            headers=_headers(api_key),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise OSINTError(f"Network error querying VirusTotal: {exc}") from exc
    _validate_response(response)
    return _format_hash(response.json())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@cached(ttl=600)
async def run_virustotal_osint(target: str, timeout_seconds: int = _DEFAULT_TIMEOUT) -> str:
    """
    Check *target* against VirusTotal's 70+ antivirus engines.

    Auto-detects the input type: IPv4 address, domain, URL, or file hash
    (MD5 / SHA-1 / SHA-256).

    Requires ``VIRUSTOTAL_API_KEY`` environment variable.

    Returns
    -------
    str
        Formatted result string or descriptive error message.
    """
    api_key = os.environ.get("VIRUSTOTAL_API_KEY", "")
    if not api_key:
        return (
            "Scan error: VIRUSTOTAL_API_KEY environment variable is not set. "
            "Get a free key at https://www.virustotal.com/gui/my-apikey"
        )

    target = target.strip()
    input_type = _detect_input_type(target)
    logger.info("Starting VirusTotal lookup for: %s (type: %s)", target, input_type)

    try:
        if input_type == "ip":
            result = await asyncio.to_thread(_lookup_ip, api_key, target, timeout_seconds)
        elif input_type == "domain":
            result = await asyncio.to_thread(_lookup_domain, api_key, target, timeout_seconds)
        elif input_type == "url":
            result = await _lookup_url(api_key, target, timeout_seconds)
        else:
            result = await asyncio.to_thread(_lookup_hash, api_key, target, timeout_seconds)
        logger.info("VirusTotal lookup complete for: %s", target)
        return result
    except OSINTError as exc:
        logger.warning("VirusTotal lookup failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during VirusTotal lookup.")
        return f"Internal error: {exc}"
