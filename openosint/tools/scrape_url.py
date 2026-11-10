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
Free tier: 5,000 requests/month — see openosint.brightdata.referral_link

# TODO: Future PR — add search_profile_social tool for social-media profile
#       extraction once ToS and rate-limit guidance is confirmed with Bright Data.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

import requests

from openosint.brightdata_response import Kind, classify
from openosint.settings_catalog import missing_from, missing_keys_extra, missing_keys_message
from openosint.tool_policy import requires_active
from openosint.tools.exceptions import OSINTError, ToolExecutionError

logger = logging.getLogger(__name__)

_API_URL = "https://api.brightdata.com/request"
_DEFAULT_TIMEOUT = 60
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _is_valid_url(url: str) -> bool:
    return bool(_URL_RE.match(url.strip()))


def _fetch_unlocker(url: str, api_key: str, zone: str, timeout: int) -> tuple[int | None, str]:
    """Return (target's own HTTP status if it was not a success, markdown body).

    format="raw" means no envelope: the body is the page. A block (CAPTCHA, anti-bot page) or a
    Bright Data/account failure raises; the target's own 404/410/401/5xx is returned, because on
    an OSINT target a removed page or profile is itself a finding.
    """
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

    error = classify(
        response,
        api_key=api_key,
        zone=zone,
        zone_env="BRIGHTDATA_UNLOCKER_ZONE",
        product="Web Unlocker",
    )
    target_status = None
    if error is not None:
        if error.kind is not Kind.TARGET_STATUS:
            raise error
        target_status = error.status_code
    elif response.status_code != 200:  # 2xx other than 200 carries no page
        raise ToolExecutionError(f"Bright Data Web Unlocker returned HTTP {response.status_code}.")

    # format="raw": body is the plain markdown string — do not json.parse it
    return target_status, response.text


_REQUIRED_SETTINGS = ["BRIGHTDATA_API_KEY", "BRIGHTDATA_UNLOCKER_ZONE"]


def also_needed(
    url: str = "",
    timeout_seconds: int = _DEFAULT_TIMEOUT,
    *,
    api_keys: dict[str, str] | None = None,
) -> str:
    """Setup guidance to add to a refusal (passive mode) when the Bright Data settings are missing too, else ""."""
    missing = missing_from(_REQUIRED_SETTINGS, api_keys, os.environ)
    return missing_keys_extra("scrape_url", missing) if missing else ""


@requires_active("scrape_url", also_needed=also_needed)
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
    missing = missing_from(_REQUIRED_SETTINGS, _k, os.environ)
    if missing:
        return missing_keys_message("scrape_url", missing)
    api_key = _k.get("BRIGHTDATA_API_KEY") or os.environ["BRIGHTDATA_API_KEY"]
    zone = _k.get("BRIGHTDATA_UNLOCKER_ZONE") or os.environ["BRIGHTDATA_UNLOCKER_ZONE"]

    url = url.strip()
    if not _is_valid_url(url):
        return "Invalid URL: must start with http:// or https://"

    logger.info("Starting Web Unlocker fetch for: %s", url)
    try:
        target_status, markdown = await asyncio.to_thread(
            _fetch_unlocker, url, api_key, zone, timeout_seconds
        )
        content = markdown.strip() if markdown.strip() else "(empty response body)"
        status_line = f"\n[Target returned HTTP {target_status}]" if target_status else ""
        result = f"[Web Unlocker] URL: {url}{status_line}\n\n{content}"
        logger.info("Web Unlocker fetch complete for: %s", url)
        return result
    except OSINTError as exc:
        logger.warning("Web Unlocker fetch failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during Web Unlocker fetch.")
        return f"Internal error: {exc}"
