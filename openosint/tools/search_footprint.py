# openosint/tools/search_footprint.py
"""
Bright Data SERP footprint tool.

Detects the entity type of the target (email, username, domain, phone, or
full name), selects entity-type-aware query templates, and runs them through
the Bright Data SERP API.  Returns structured results plus graph-compatible
``[Footprint] URL:`` lines that the Entity Correlation Graph extractor parses.

Differs from ``search_dorks_live``, which uses the generic ``_DORK_TEMPLATES``
regardless of entity type.  This tool selects queries optimised for what the
target actually is.

Request format: POST https://api.brightdata.com/request
  { zone, url, format: "raw", data_format: "parsed_light" }
With format="raw" + data_format="parsed_light", response.json() returns the
parsed SERP data directly as {"organic": [...]} — no envelope wrapper.

Requires BRIGHTDATA_API_KEY and BRIGHTDATA_SERP_ZONE environment variables.

OpenOSINT earns a referral commission if you sign up through our link.
Free tier: 5,000 requests/month — see openosint.brightdata.BRIGHTDATA_LINK_CLI
"""

from __future__ import annotations

import asyncio
import logging
import os
import urllib.parse
from urllib.parse import urlparse

import requests

from openosint.brightdata import BRIGHTDATA_LINK_CLI
from openosint.regexes import detect_entity_kind
from openosint.tools.exceptions import OSINTError, ToolExecutionError

logger = logging.getLogger(__name__)

_API_URL = "https://api.brightdata.com/request"
_DEFAULT_TIMEOUT = 30
_DEFAULT_MAX_QUERIES = 3
_GOOGLE_SEARCH_BASE = "https://www.google.com/search?q="

_MISSING_KEY_MSG = (
    "Scan error: BRIGHTDATA_API_KEY environment variable is not set. "
    "A free tier (5,000 requests/month) is available — "
    f"sign up at {BRIGHTDATA_LINK_CLI}"
)
_MISSING_ZONE_MSG = (
    "Scan error: BRIGHTDATA_SERP_ZONE environment variable is not set. "
    "Set it to your Bright Data SERP API zone name (e.g. 'serp_api1'). "
    f"Create a zone at {BRIGHTDATA_LINK_CLI}"
)

# ---------------------------------------------------------------------------
# Entity-type-aware query templates
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, list[str]] = {
    "email": [
        '"{target}"',
        '"{target}" (site:pastebin.com OR site:github.com OR site:trello.com)',
        '"{target}" -site:google.com',
    ],
    "username": [
        '"{target}"',
        '"{target}" (site:github.com OR site:twitter.com OR site:reddit.com OR site:linkedin.com)',
        '"{target}" profile',
    ],
    "domain": [
        "site:{target}",
        '"{target}" -site:{target}',
        'inurl:"{target}"',
    ],
    "phone": [
        '"{target}"',
        '"{target}" (site:truecaller.com OR site:whitepages.com OR site:spokeo.com)',
    ],
    "person": [
        '"{target}"',
        '"{target}" (site:linkedin.com OR site:twitter.com OR site:facebook.com)',
        '"{target}" resume OR cv OR portfolio',
    ],
}

# ip/url/hash — SERP footprint not applicable for these entity types
_UNSUPPORTED_KINDS = frozenset({"ip", "url", "hash"})


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------


def _build_google_url(query: str) -> str:
    """Build a Google search URL with q= first (improves Bright Data success rate)."""
    return f"{_GOOGLE_SEARCH_BASE}{urllib.parse.quote(query)}&hl=en&gl=us"


def _fetch_serp(url: str, api_key: str, zone: str, timeout: int) -> dict:
    try:
        response = requests.post(
            _API_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={"zone": zone, "url": url, "format": "raw", "data_format": "parsed_light"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise OSINTError(f"Network error querying Bright Data SERP: {exc}") from exc

    if response.status_code == 401:
        raise OSINTError("Bright Data SERP: invalid API key.")
    if response.status_code == 403:
        raise OSINTError("Bright Data SERP: forbidden — check zone permissions.")
    if response.status_code == 429:
        raise OSINTError("Bright Data SERP: rate limit exceeded.")
    if response.status_code != 200:
        raise ToolExecutionError(f"Bright Data SERP returned HTTP {response.status_code}.")

    # format="raw" + data_format="parsed_light": body IS the parsed JSON dict
    return response.json()


def _extract_organic(data: dict) -> list[dict]:
    results = []
    for rank, item in enumerate(data.get("organic", [])[:5], start=1):
        link = item.get("link", "") or item.get("url", "")
        if not link:
            continue
        results.append(
            {
                "rank": rank,
                "title": item.get("title", ""),
                "url": link,
                "display_url": item.get("display_link", "") or urlparse(link).netloc,
                "snippet": (item.get("description", "") or item.get("snippet", ""))[:200],
            }
        )
    return results


def _domain_from_url(url: str) -> str:
    """Extract netloc from a URL, stripping www. prefix."""
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_footprint_osint(
    target: str,
    max_queries: int = _DEFAULT_MAX_QUERIES,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
    *,
    api_keys: dict[str, str] | None = None,
) -> dict | str:
    """
    Collect a target's public search-engine footprint via the Bright Data SERP API.

    Detects the entity type of *target* (email, username, domain, phone, or
    full name) and runs entity-type-aware Google search queries.  Returns
    structured results (title, URL, snippet, rank) plus ``[Footprint] URL:``
    lines for the Entity Correlation Graph extractor.

    Parameters
    ----------
    target:
        Any OSINT target: email address, username, domain, phone number, or
        full name.
    max_queries:
        Maximum number of SERP calls to make (default 3).  Each call is
        billable — keep this low to stay within the free-tier budget.
    timeout_seconds:
        Per-request HTTP timeout.

    Requires ``BRIGHTDATA_API_KEY`` and ``BRIGHTDATA_SERP_ZONE`` environment variables.
    OpenOSINT earns a referral commission if you sign up through our link.

    Returns
    -------
    dict | str
        Structured footprint report with graph-compatible URL lines, or a
        descriptive error message.
    """
    _k = api_keys or {}
    api_key = _k.get("BRIGHTDATA_API_KEY") or os.environ.get("BRIGHTDATA_API_KEY", "")
    if not api_key:
        return _MISSING_KEY_MSG

    zone = _k.get("BRIGHTDATA_SERP_ZONE") or os.environ.get("BRIGHTDATA_SERP_ZONE", "")
    if not zone:
        return _MISSING_ZONE_MSG

    target = target.strip()
    if not target:
        return "Invalid input: target must not be empty."

    kind = detect_entity_kind(target)
    if kind in _UNSUPPORTED_KINDS:
        return (
            f"Scan error: footprint search is not supported for entity type '{kind}'. "
            "Use search_virustotal, search_ip, or search_shodan instead."
        )

    templates = _TEMPLATES.get(kind, _TEMPLATES["person"])
    queries = [t.format(target=target) for t in templates[:max_queries]]

    logger.info(
        "Starting footprint search for '%s' (type=%s, %d queries)", target, kind, len(queries)
    )

    seen_urls: set[str] = set()
    seen_domains: set[str] = set()
    discovered_urls: list[str] = []
    error_count = 0
    
    structured_results = {
        "target": target,
        "target_type": kind,
        "queries": [],
        "discovered_urls": [],
        "seen_domains": []
    }

    for i, query in enumerate(queries, start=1):
        google_url = _build_google_url(query)
        
        query_data = {
            "query": query,
            "results": [],
            "error": None
        }

        try:
            data = await asyncio.to_thread(
                _fetch_serp, google_url, api_key, zone, timeout_seconds
            )
            results = _extract_organic(data)
            if results:
                query_data["results"] = results
                for r in results:
                    url_key = r["url"].rstrip("/")
                    if url_key in seen_urls:
                        continue
                    seen_urls.add(url_key)
                    discovered_urls.append(r["url"])
                    
                    domain = _domain_from_url(r["url"])
                    if domain and domain not in seen_domains:
                        seen_domains.add(domain)

        except OSINTError as exc:
            error_count += 1
            logger.warning("Footprint SERP query failed: %s", exc)
            query_data["error"] = str(exc)
        except Exception as exc:
            error_count += 1
            logger.exception("Unexpected error in footprint SERP query.")
            query_data["error"] = f"internal error: {exc}"
            
        structured_results["queries"].append(query_data)

    if error_count == len(queries):
        return (
            "Scan error: all SERP requests failed. "
            "Check BRIGHTDATA_API_KEY and BRIGHTDATA_SERP_ZONE."
        )

    structured_results["discovered_urls"] = discovered_urls
    structured_results["seen_domains"] = list(seen_domains)

    logger.info(
        "Footprint search complete for '%s': %d URLs, %d domains",
        target,
        len(discovered_urls),
        len(seen_domains),
    )
    return structured_results
