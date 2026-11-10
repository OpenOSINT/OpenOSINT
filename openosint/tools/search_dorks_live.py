# openosint/tools/search_dorks_live.py
"""
Bright Data SERP API integration.

Executes Google dork queries for a target through the Bright Data SERP API,
returning structured results (title, URL, snippet) for each dork.

`generate_dorks` remains fully offline and unchanged; this is a separate,
opt-in tool that requires a Bright Data account.

Request format: POST https://api.brightdata.com/request
  { zone, url, format: "raw", data_format: "parsed_light" }
With format="raw" + data_format="parsed_light", response.json() returns the
parsed SERP data directly as {"organic": [...]} — no envelope wrapper.

Requires BRIGHTDATA_API_KEY and BRIGHTDATA_SERP_ZONE environment variables.

OpenOSINT earns a referral commission if you sign up through our link.
Free tier: 5,000 requests/month — see openosint.brightdata.referral_link
"""

from __future__ import annotations

import asyncio
import logging
import os
import urllib.parse
from collections import Counter

import requests

from openosint.brightdata_response import BrightDataError, body_preview, brd_headers, classify
from openosint.settings_catalog import missing_from, missing_keys_message
from openosint.tools.exceptions import OSINTError
from openosint.tools.generate_dorks import _DORK_TEMPLATES

logger = logging.getLogger(__name__)

_API_URL = "https://api.brightdata.com/request"
_DEFAULT_TIMEOUT = 30
_DEFAULT_MAX_DORKS = 5
_GOOGLE_SEARCH_BASE = "https://www.google.com/search?q="
_UNRESOLVED_URL = "(unresolved)"
_GOOGLE_REDIRECT_PATHS = ("/url", "/goto")
_FORBIDDEN_STATUS = 403

# Kept as the name this module has always exported; the class lives with the classifier.
SerpFetchError = BrightDataError


def _build_google_url(dork_query: str) -> str:
    return f"{_GOOGLE_SEARCH_BASE}{urllib.parse.quote(dork_query)}&hl=en&gl=us"


def _serp_error_detail(response: requests.Response, api_key: str) -> str:
    content_type = response.headers.get("content-type", "unknown")
    return f"HTTP {response.status_code}, content-type={content_type!r}, body={body_preview(response, api_key)!r}"


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

    error = classify(
        response, api_key=api_key, zone=zone, zone_env="BRIGHTDATA_SERP_ZONE", product="SERP API"
    )
    if error is not None:
        raise error
    if brd_headers(response)[0] is None and not (response.text or "").strip():
        raise SerpFetchError(
            f"Bright Data SERP: empty response body. {_serp_error_detail(response, api_key)}"
        )

    # format="raw" + data_format="parsed_light": response body IS the parsed JSON dict
    try:
        return response.json()
    except ValueError as exc:
        raise SerpFetchError(
            f"Bright Data SERP: non-JSON response body. {_serp_error_detail(response, api_key)}"
        ) from exc


def _is_absolute_http_url(value: str) -> bool:
    parsed = urllib.parse.urlsplit(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _clean_link(item: dict) -> str | None:
    """Resolve a real absolute http(s) URL from a SERP organic item, or None.

    Handles three shapes seen in Bright Data SERP responses:
      - a clean absolute URL
      - a Google redirect (``/url?q=...`` or ``/goto?url=...``) whose query
        parameter is itself an absolute URL — unwrapped and returned
      - an absolute URL with trailing snippet text appended — first
        whitespace-delimited token is kept

    Opaque Google redirect tokens (``/goto?url=CAES...``) are not decodable
    and correctly resolve to None.
    """
    raw = item.get("link") or item.get("url") or ""
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip()

    parsed = urllib.parse.urlsplit(raw)
    if parsed.path in _GOOGLE_REDIRECT_PATHS:
        query = urllib.parse.parse_qs(parsed.query)
        target = (query.get("q") or query.get("url") or [None])[0]
        return target if target and _is_absolute_http_url(target) else None

    if raw.startswith("http://") or raw.startswith("https://"):
        token = raw.split()[0]
        return token if _is_absolute_http_url(token) else None

    return None


def _extract_organic(data: dict) -> list[dict]:
    organic = data.get("organic", [])
    results = []
    for item in organic[:5]:
        title = item.get("title", "")
        snippet = item.get("description", "") or item.get("snippet", "")
        results.append({"title": title, "url": _clean_link(item), "snippet": snippet})
    return results


def _failure_label(exc: Exception) -> str:
    if isinstance(exc, SerpFetchError):
        if exc.error_code and exc.error_code != "auth":
            return f"{exc.status_code} {exc.error_code}" if exc.status_code else exc.error_code
        if exc.status_code:
            return str(exc.status_code)
        return "unknown"
    if isinstance(exc, OSINTError):
        return "network_error"
    return "internal_error"


def _summarize_failures(labels: list[str], total: int, mention_credentials: bool) -> str:
    counts = Counter(labels)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    detail = ", ".join(f"{count}x {label}" for label, count in ordered)
    summary = f"Scan error: all {total} dorks failed: {detail}."
    if mention_credentials:
        summary += " Check BRIGHTDATA_API_KEY and BRIGHTDATA_SERP_ZONE."
    return summary


async def run_dorks_live_osint(
    target: str,
    max_dorks: int = _DEFAULT_MAX_DORKS,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
    *,
    api_keys: dict[str, str] | None = None,
) -> str:
    """
    Execute Google dork queries for *target* via the Bright Data SERP API.

    Reuses the same dork templates as ``generate_dorks`` but fetches live
    search results instead of generating URLs. Each dork is a separate API
    call — Bright Data bills per successful request.

    Requires ``BRIGHTDATA_API_KEY`` and ``BRIGHTDATA_SERP_ZONE`` environment variables.
    OpenOSINT earns a referral commission if you sign up through our link.

    Returns
    -------
    str
        Formatted results or descriptive error message.
    """
    _k = api_keys or {}
    missing = missing_from(["BRIGHTDATA_API_KEY", "BRIGHTDATA_SERP_ZONE"], _k, os.environ)
    if missing:
        return missing_keys_message("search_dorks_live", missing)
    api_key = _k.get("BRIGHTDATA_API_KEY") or os.environ["BRIGHTDATA_API_KEY"]
    zone = _k.get("BRIGHTDATA_SERP_ZONE") or os.environ["BRIGHTDATA_SERP_ZONE"]

    target = target.strip()
    if not target:
        return "Invalid input: target must not be empty."

    dorks = _DORK_TEMPLATES[:max_dorks]
    logger.info("Starting live dork search for '%s' (%d dorks)", target, len(dorks))

    lines = [f"Bright Data live dork search for '{target}' ({len(dorks)} queries):\n"]
    error_count = 0
    failure_labels: list[str] = []
    auth_failure_seen = False
    stop_message: str | None = None
    attempted = 0

    for template in dorks:
        attempted += 1
        query = template.format(target=target)
        google_url = _build_google_url(query)
        lines.append(f"[+] Dork: {query}")
        try:
            data = await asyncio.to_thread(_fetch_serp, google_url, api_key, zone, timeout_seconds)
            results = _extract_organic(data)
            if results:
                for r in results:
                    lines.append(f"    Title:   {r['title']}")
                    lines.append(f"    URL:     {r['url'] or _UNRESOLVED_URL}")
                    if r["snippet"]:
                        lines.append(f"    Snippet: {r['snippet'][:200]}")
                    lines.append("")
            else:
                lines.append("    (no organic results)")
                lines.append("")
        except OSINTError as exc:
            error_count += 1
            failure_labels.append(_failure_label(exc))
            if isinstance(exc, SerpFetchError) and exc.status_code == _FORBIDDEN_STATUS:
                auth_failure_seen = True
            logger.warning("Dork %r failed: %s", query, exc)
            logger.debug("Dork %r failure detail", query, exc_info=True)
            if getattr(exc, "stop_batch", False):
                stop_message = str(exc)  # every further dork would fail the same way
                break
            lines.append(f"    (error: {exc})")
            lines.append("")
        except Exception as exc:
            error_count += 1
            failure_labels.append(_failure_label(exc))
            logger.warning("Dork %r failed: %s", query, exc)
            logger.debug("Dork %r failure detail", query, exc_info=True)
            lines.append(f"    (internal error: {exc})")
            lines.append("")

    if stop_message:
        if error_count == attempted:
            return f"Scan error: {stop_message}"
        lines.append(f"[stopped early after {attempted - 1} of {len(dorks)} dorks] {stop_message}")
        return "\n".join(lines)

    if error_count == len(dorks):
        return _summarize_failures(failure_labels, len(dorks), auth_failure_seen)

    logger.info("Live dork search complete for: %s", target)
    return "\n".join(lines)
