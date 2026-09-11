# openosint/tools/scrape_url.py
"""
Bright Data Web Unlocker integration.

Fetches any public URL through the Bright Data Web Unlocker API,
bypassing bot-protection (Cloudflare, CAPTCHA, etc.) and returning
clean Markdown via the API's native ``data_format: "markdown"`` conversion.

Request format: POST https://api.brightdata.com/request
  { zone, url, format: "raw", data_format: "markdown" }
With format="raw", the HTTP response body IS the markdown string directly.
There is no {status_code, headers, body} envelope. Failures are detected via
the HTTP status code of the /request call itself.

Requires BRIGHTDATA_API_KEY and BRIGHTDATA_UNLOCKER_ZONE environment variables.

OpenOSINT earns a referral commission if you sign up through our link.
Free tier: 5,000 requests/month — see openosint.brightdata.BRIGHTDATA_LINK_CLI

# TODO: Future PR — add search_profile_social tool for social-media profile
#       extraction once ToS and rate-limit guidance is confirmed with Bright Data.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

import requests

from openosint.brightdata import BRIGHTDATA_LINK_CLI
from openosint.env import missing_var_message
from openosint.tools.exceptions import OSINTError, ToolExecutionError

logger = logging.getLogger(__name__)

_API_URL = "https://api.brightdata.com/request"
_DEFAULT_TIMEOUT = 60
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _missing_key_msg() -> str:
    return (
        f"{missing_var_message('BRIGHTDATA_API_KEY')} "
        "A free tier (5,000 requests/month) is available — "
        f"sign up at {BRIGHTDATA_LINK_CLI}"
    )


def _missing_zone_msg() -> str:
    return (
        f"{missing_var_message('BRIGHTDATA_UNLOCKER_ZONE')} "
        "Set it to your Bright Data Web Unlocker zone name (e.g. 'web_unlocker1'). "
        f"Create a zone at {BRIGHTDATA_LINK_CLI}"
    )


def _is_valid_url(url: str) -> bool:
    return bool(_URL_RE.match(url.strip()))


def _fetch_unlocker(url: str, api_key: str, zone: str, timeout: int) -> str:
    """Return the markdown body string directly (format="raw" means no envelope)."""
    try:
        response = requests.post(
            _API_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={"zone": zone, "url": url, "format": "raw", "data_format": "markdown"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise OSINTError(f"Network error querying Bright Data Web Unlocker: {exc}") from exc

    if response.status_code == 401:
        raise OSINTError("Bright Data Web Unlocker: invalid API key.")
    if response.status_code == 403:
        raise OSINTError("Bright Data Web Unlocker: forbidden — check zone permissions.")
    if response.status_code == 429:
        raise OSINTError("Bright Data Web Unlocker: rate limit exceeded.")
    if response.status_code != 200:
        raise ToolExecutionError(
            f"Bright Data Web Unlocker returned HTTP {response.status_code}."
        )

    # format="raw": body is the plain markdown string — do not json.parse it
    return response.text


async def run_scrape_url_osint(
    url: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
    *,
    api_keys: dict[str, str] | None = None,
) -> str:
    """
    Fetch *url* through Bright Data Web Unlocker and return clean Markdown.

    Bypasses bot-protection (Cloudflare, CAPTCHA, etc.). Uses the API's
    native ``data_format: "markdown"`` conversion so the AI receives
    clean, readable content rather than raw HTML.

    With ``format: "raw"``, the response body is the markdown string directly —
    there is no JSON envelope to unwrap.

    Requires ``BRIGHTDATA_API_KEY`` and ``BRIGHTDATA_UNLOCKER_ZONE`` environment variables.
    OpenOSINT earns a referral commission if you sign up through our link.

    Returns
    -------
    str
        Markdown content with a URL header line, or descriptive error message.
    """
    _k = api_keys or {}
    api_key = _k.get("BRIGHTDATA_API_KEY") or os.environ.get("BRIGHTDATA_API_KEY", "")
    if not api_key:
        return _missing_key_msg()

    zone = _k.get("BRIGHTDATA_UNLOCKER_ZONE") or os.environ.get("BRIGHTDATA_UNLOCKER_ZONE", "")
    if not zone:
        return _missing_zone_msg()

    url = url.strip()
    if not _is_valid_url(url):
        return "Invalid URL: must start with http:// or https://"

    logger.info("Starting Web Unlocker fetch for: %s", url)
    try:
        markdown = await asyncio.to_thread(_fetch_unlocker, url, api_key, zone, timeout_seconds)
        content = markdown.strip() if markdown.strip() else "(empty response body)"
        result = f"[Web Unlocker] URL: {url}\n\n{content}"
        logger.info("Web Unlocker fetch complete for: %s", url)
        return result
    except OSINTError as exc:
        logger.warning("Web Unlocker fetch failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during Web Unlocker fetch.")
        return f"Internal error: {exc}"
