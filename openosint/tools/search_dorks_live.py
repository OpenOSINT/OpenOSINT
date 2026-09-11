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
Free tier: 5,000 requests/month — see openosint.brightdata.BRIGHTDATA_LINK_CLI
"""

from __future__ import annotations

import asyncio
import logging
import os
import urllib.parse
from collections import Counter

import requests

from openosint.brightdata import BRIGHTDATA_LINK_CLI
from openosint.env import missing_var_message
from openosint.tools.exceptions import OSINTError, ToolExecutionError
from openosint.tools.generate_dorks import _DORK_TEMPLATES

logger = logging.getLogger(__name__)

_API_URL = "https://api.brightdata.com/request"
_DEFAULT_TIMEOUT = 30
_DEFAULT_MAX_DORKS = 5
_GOOGLE_SEARCH_BASE = "https://www.google.com/search?q="
_BODY_PREVIEW_LEN = 200
_UNRESOLVED_URL = "(unresolved)"
_GOOGLE_REDIRECT_PATHS = ("/url", "/goto")
_RETRY_HINT = "query temporarily blocked by Bright Data, retry after 15 seconds"
_VERIFICATION_HINT = "search engine returned a verification page; not billed"
_RETRY_ERROR_CODES = frozenset({"failed_query_rejected", "repeat_query_rejected"})
_VERIFICATION_ERROR_CODES = frozenset({"captcha", "verifying"})
_AUTH_STATUS_CODES = (401, 403)


class SerpFetchError(ToolExecutionError):
    """Bright Data reported a failed SERP fetch: bad status (HTTP or x-brd-*), or unparsable body."""

    def __init__(
        self, message: str, *, status_code: int | None = None, error_code: str | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


def _missing_key_msg() -> str:
    return (
        f"{missing_var_message('BRIGHTDATA_API_KEY')} "
        "A free tier (5,000 requests/month) is available — "
        f"sign up at {BRIGHTDATA_LINK_CLI}"
    )


def _missing_zone_msg() -> str:
    return (
        f"{missing_var_message('BRIGHTDATA_SERP_ZONE')} "
        "Set it to your Bright Data SERP API zone name (e.g. 'serp_api1'). "
        f"Create a zone at {BRIGHTDATA_LINK_CLI}"
    )


def _build_google_url(dork_query: str) -> str:
    return f"{_GOOGLE_SEARCH_BASE}{urllib.parse.quote(dork_query)}&hl=en&gl=us"


def _redact(text: str, api_key: str) -> str:
    return text.replace(api_key, "***REDACTED***") if api_key else text


def _serp_error_detail(response: requests.Response, api_key: str) -> str:
    content_type = response.headers.get("content-type", "unknown")
    body_preview = _redact((response.text or "")[:_BODY_PREVIEW_LEN], api_key)
    return f"HTTP {response.status_code}, content-type={content_type!r}, body={body_preview!r}"


def _brd_error_headers(response: requests.Response) -> tuple[int | None, str | None, str | None]:
    """Read Bright Data's real outcome from x-brd-* response headers.

    Bright Data returns HTTP 200 at the API level even when the underlying
    fetch failed; the real status/error code/message live in these headers
    instead. Proxy-layer failures use the x-brd-err-code/x-brd-err-msg
    spelling rather than x-brd-error-code/x-brd-error.
    """
    headers = response.headers
    raw_status = headers.get("x-brd-status-code")
    error_code = headers.get("x-brd-error-code") or headers.get("x-brd-err-code")
    error_message = headers.get("x-brd-error") or headers.get("x-brd-err-msg")
    status = int(raw_status) if raw_status and raw_status.strip().isdigit() else None
    return status, error_code, error_message


def _brd_failure_message(status: int, error_code: str | None, error_message: str | None) -> str:
    text = f"Bright Data {status}"
    if error_code:
        text += f" {error_code}"
    if error_message:
        text += f": {error_message}"
    if error_code in _RETRY_ERROR_CODES:
        text += f" — {_RETRY_HINT}"
    elif error_code in _VERIFICATION_ERROR_CODES:
        text += f" — {_VERIFICATION_HINT}"
    return text


def _auth_error(response: requests.Response, api_key: str) -> SerpFetchError:
    kind = (
        "invalid API key" if response.status_code == 401 else "forbidden — check zone permissions"
    )
    body_preview = _redact((response.text or "")[:_BODY_PREVIEW_LEN], api_key)
    message = f"Bright Data SERP: {kind}. HTTP {response.status_code}, body={body_preview!r}"
    if "token expired" in (response.text or "").lower():
        message += " — Bright Data API key expired — renew it in the Bright Data dashboard."
    return SerpFetchError(message, status_code=response.status_code, error_code="auth")


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

    if response.status_code in _AUTH_STATUS_CODES:
        raise _auth_error(response, api_key)

    brd_status, brd_error_code, brd_error_message = _brd_error_headers(response)
    if brd_status is not None:
        if not (200 <= brd_status < 300):
            raise SerpFetchError(
                _brd_failure_message(brd_status, brd_error_code, brd_error_message),
                status_code=brd_status,
                error_code=brd_error_code,
            )
    elif response.status_code != 200:
        raise SerpFetchError(
            f"Bright Data SERP: unexpected response. {_serp_error_detail(response, api_key)}",
            status_code=response.status_code,
        )
    elif not (response.text or "").strip():
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
    api_key = _k.get("BRIGHTDATA_API_KEY") or os.environ.get("BRIGHTDATA_API_KEY", "")
    if not api_key:
        return _missing_key_msg()

    zone = _k.get("BRIGHTDATA_SERP_ZONE") or os.environ.get("BRIGHTDATA_SERP_ZONE", "")
    if not zone:
        return _missing_zone_msg()

    target = target.strip()
    if not target:
        return "Invalid input: target must not be empty."

    dorks = _DORK_TEMPLATES[:max_dorks]
    logger.info("Starting live dork search for '%s' (%d dorks)", target, len(dorks))

    lines = [f"Bright Data live dork search for '{target}' ({len(dorks)} queries):\n"]
    error_count = 0
    failure_labels: list[str] = []
    auth_failure_seen = False

    for template in dorks:
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
            if isinstance(exc, SerpFetchError) and exc.status_code in _AUTH_STATUS_CODES:
                auth_failure_seen = True
            logger.warning("Dork %r failed: %s", query, exc)
            logger.debug("Dork %r failure detail", query, exc_info=True)
            lines.append(f"    (error: {exc})")
            lines.append("")
        except Exception as exc:
            error_count += 1
            failure_labels.append(_failure_label(exc))
            logger.warning("Dork %r failed: %s", query, exc)
            logger.debug("Dork %r failure detail", query, exc_info=True)
            lines.append(f"    (internal error: {exc})")
            lines.append("")

    if error_count == len(dorks):
        return _summarize_failures(failure_labels, len(dorks), auth_failure_seen)

    logger.info("Live dork search complete for: %s", target)
    return "\n".join(lines)
