# openosint/tools/search_censys.py
"""
Censys integration module.

Queries the Censys Search API for internet-facing infrastructure data.
Auto-detects whether the input is an IPv4 address or a domain name.

  - IP address  → CensysHosts().view(ip) — open ports, services, ASN, location
  - Domain      → CensysCerts().search() — certificate history, SANs, issuer

Requires CENSYS_API_ID and CENSYS_SECRET environment variables.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from openosint.env import missing_var_message
from openosint.proxy import get_requests_proxies
from openosint.tools.exceptions import OSINTError

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30
_IP_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_ip_address(target: str) -> bool:
    """Return True when target looks like an IPv4 address."""
    return bool(_IP_RE.match(target.strip()))


def _format_ip_result(data: dict, ip: str) -> str:
    lines = ["[Censys] Type: ip", f"[Censys] IP: {ip}"]

    services = data.get("services", [])
    ports = sorted({str(s.get("port")) for s in services if s.get("port")})
    if ports:
        lines.append(f"[Censys] Open Ports: {', '.join(ports[:20])}")

    svc_names: list[str] = []
    seen: set[str] = set()
    for s in services:
        name = s.get("service_name", "")
        if name and name not in seen:
            seen.add(name)
            svc_names.append(name)
    if svc_names:
        lines.append(f"[Censys] Services: {', '.join(svc_names[:20])}")

    asn_data = data.get("autonomous_system", {})
    asn = asn_data.get("asn", "")
    asn_name = asn_data.get("name", "")
    if asn:
        lines.append(f"[Censys] ASN: AS{asn} {asn_name}".rstrip())

    location = data.get("location", {})
    country = location.get("country", "")
    if country:
        lines.append(f"[Censys] Country: {country}")

    last_updated = data.get("last_updated_at", "")
    if last_updated:
        lines.append(f"[Censys] Last Updated: {last_updated[:10]}")

    return "\n".join(lines)


def _format_domain_result(results: list, domain: str) -> str:
    lines = [
        "[Censys] Type: domain",
        f"[Censys] Domain: {domain}",
        f"[Censys] Certificates Found: {len(results)}",
    ]

    if not results:
        return "\n".join(lines)

    first = results[0]
    parsed = first.get("parsed", {})

    issuer_orgs = parsed.get("issuer", {}).get("organization", [])
    if isinstance(issuer_orgs, list) and issuer_orgs:
        lines.append(f"[Censys] Issuer: {issuer_orgs[0]}")
    elif isinstance(issuer_orgs, str) and issuer_orgs:
        lines.append(f"[Censys] Issuer: {issuer_orgs}")

    names = parsed.get("names", [])
    if names:
        lines.append(f"[Censys] SANs: {', '.join(names[:10])}")

    starts: list[str] = []
    ends: list[str] = []
    for r in results:
        validity = r.get("parsed", {}).get("validity", {})
        if validity.get("start"):
            starts.append(validity["start"])
        if validity.get("end"):
            ends.append(validity["end"])

    if starts:
        lines.append(f"[Censys] First Seen: {min(starts)[:10]}")
    if ends:
        lines.append(f"[Censys] Last Seen: {max(ends)[:10]}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_censys_osint(target: str, timeout_seconds: int = _DEFAULT_TIMEOUT, *, api_keys: dict[str, str] | None = None) -> str:
    """
    Run a Censys lookup for *target*.

    Auto-detects input type: IPv4 address → host view (open ports, services,
    ASN, location); domain → certificate search (SANs, issuer, validity dates).

    Requires ``CENSYS_API_ID`` and ``CENSYS_SECRET`` environment variables.

    Returns
    -------
    str
        Formatted result string or descriptive error message.
    """
    _k = api_keys or {}
    api_id = _k.get("CENSYS_API_ID") or os.environ.get("CENSYS_API_ID", "")
    api_secret = _k.get("CENSYS_SECRET") or os.environ.get("CENSYS_SECRET", "")

    if not api_id:
        return f"{missing_var_message('CENSYS_API_ID')} Get credentials at https://censys.io/account"
    if not api_secret:
        return f"{missing_var_message('CENSYS_SECRET')} Get credentials at https://censys.io/account"

    try:
        from censys.search import CensysHosts  # type: ignore
    except ImportError:
        return "Scan error: 'censys' library is not installed. Install it with: pip install censys"

    target = target.strip()
    logger.info("Starting Censys lookup for: %s", target)

    try:
        if _is_ip_address(target):
            hosts = CensysHosts(api_id=api_id, api_secret=api_secret, proxies=get_requests_proxies())
            data = await asyncio.wait_for(
                asyncio.to_thread(hosts.view, target),
                timeout=float(timeout_seconds),
            )
            result = _format_ip_result(data, target)
        else:
            try:
                from censys.search import CensysCerts  # type: ignore

                certs = CensysCerts(api_id=api_id, api_secret=api_secret, proxies=get_requests_proxies())
                query = f"parsed.names: {target}"
                search_results: list = await asyncio.wait_for(
                    asyncio.to_thread(
                        lambda: list(
                            certs.search(
                                query,
                                fields=[
                                    "parsed.names",
                                    "parsed.issuer.organization",
                                    "parsed.validity.start",
                                    "parsed.validity.end",
                                ],
                                max_records=50,
                            )
                        )
                    ),
                    timeout=float(timeout_seconds),
                )
            except ImportError:
                hosts = CensysHosts(api_id=api_id, api_secret=api_secret, proxies=get_requests_proxies())
                search_results = await asyncio.wait_for(
                    asyncio.to_thread(
                        lambda: list(
                            hosts.search(
                                f"services.tls.certificates.leaf_data.names: {target}",
                                per_page=10,
                            )
                        )
                    ),
                    timeout=float(timeout_seconds),
                )
            result = _format_domain_result(search_results, target)

        logger.info("Censys lookup complete for: %s", target)
        return result

    except asyncio.TimeoutError:
        return f"Scan error: Censys request timed out after {timeout_seconds}s."
    except OSINTError as exc:
        logger.warning("Censys lookup failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        exc_str = str(exc).lower()
        if "rate" in exc_str or "429" in exc_str:
            return "Censys rate limit reached. Try again later."
        if "not found" in exc_str or "404" in exc_str:
            return "No Censys data found for target."
        if "401" in exc_str or "unauthorized" in exc_str or "forbidden" in exc_str:
            return "Censys authentication failed. Check your CENSYS_API_ID and CENSYS_SECRET."
        logger.exception("Unexpected error during Censys lookup.")
        return f"Internal error: {exc}"
