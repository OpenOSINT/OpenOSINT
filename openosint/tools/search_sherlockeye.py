# openosint/tools/search_sherlockeye.py
"""
Sherlockeye integration module.

Reverse Lookup & AI-Powered OSINT search across email, phone, username, domain,
IP, name, CPF, and CNPJ via the Sherlockeye API. Uses synchronous search
with polling fallback when the API returns a processing status.
Requires SHERLOCKEYE_API_KEY.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

import aiohttp

logger = logging.getLogger(__name__)

_API_BASE = "https://api.sherlockeye.io"
_DEFAULT_TIMEOUT = 120
_POLL_INTERVAL = 5
_MAX_RESULTS_DISPLAY = 50

_MISSING_KEY_ERROR = (
    "Scan error: SHERLOCKEYE_API_KEY environment variable is not set. "
    "Get a key at https://app.sherlockeye.io/api"
)

_EXPLICIT_QUERY_RE = re.compile(
    r"^(email|phone|name|domain|ip|username|cpf|cnpj)\s*:\s*(?:\"([^\"]+)\"|(.+))$",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_IP_RE = re.compile(
    r"^("
    r"(\d{1,3}\.){3}\d{1,3}"
    r"|"
    r"([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}"
    r")$"
)
_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$")
_PHONE_RE = re.compile(r"^\+?[\d\s().\-]{8,20}$")
_CPF_RE = re.compile(r"^\d{11}$")
_CNPJ_RE = re.compile(r"^\d{14}$")

_TERMINAL_STATUSES = frozenset({"complete", "completed", "failed", "partial"})


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def _infer_search_type(value: str) -> str:
    stripped = value.strip()
    lowered = stripped.lower()
    if _EMAIL_RE.match(lowered):
        return "email"
    if _IP_RE.match(stripped):
        return "ip"
    digits = _digits_only(stripped)
    if _CPF_RE.match(digits):
        return "cpf"
    if _CNPJ_RE.match(digits):
        return "cnpj"
    if _PHONE_RE.match(stripped) and len(digits) >= 8:
        return "phone"
    if _DOMAIN_RE.match(lowered) and "@" not in lowered:
        return "domain"
    if " " in stripped:
        return "name"
    return "username"


def _parse_query(query: str) -> tuple[str, str]:
    query = query.strip()
    if not query:
        raise ValueError("Query cannot be empty.")
    match = _EXPLICIT_QUERY_RE.match(query)
    if match:
        search_type = match.group(1).lower()
        value = (match.group(2) or match.group(3) or "").strip()
        if not value:
            raise ValueError("Query value cannot be empty.")
        return search_type, value
    return _infer_search_type(query), query


def _build_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _raise_for_api_error(status: int, payload: dict | None) -> None:
    message = "Unknown Sherlockeye API error."
    if isinstance(payload, dict):
        message = payload.get("message") or message
    if status in (401, 403):
        raise ValueError(f"Sherlockeye: invalid API key or access denied — {message}")
    if status == 429:
        raise ValueError(f"Sherlockeye: rate limit or credits exceeded — {message}")
    if status in (400, 422):
        raise ValueError(f"Sherlockeye: invalid request — {message}")
    if status >= 500:
        raise ValueError(f"Sherlockeye server error (HTTP {status}) — {message}")
    if status != 200:
        raise ValueError(f"Sherlockeye returned HTTP {status} — {message}")


async def _api_request(
    session: aiohttp.ClientSession,
    method: str,
    path: str,
    *,
    json_payload: dict | None = None,
) -> dict:
    url = f"{_API_BASE}{path}"
    async with session.request(method, url, json=json_payload) as resp:
        try:
            body = await resp.json()
        except aiohttp.ContentTypeError:
            body = None
        if resp.status >= 400:
            _raise_for_api_error(resp.status, body if isinstance(body, dict) else None)
        if not isinstance(body, dict):
            raise ValueError("Sherlockeye returned an invalid JSON response.")
        return body


def _format_result_item(item: dict, index: int) -> list[str]:
    source = item.get("source", "unknown")
    attributes = item.get("attributes") or {}
    lines = [f"  [{index}] Source: {source}"]
    if attributes:
        for key, val in list(attributes.items())[:12]:
            lines.append(f"      {key}: {val}")
    return lines


def _format_search_response(data: dict, query_label: str) -> str:
    status = data.get("status", "unknown")
    search_type = data.get("type", "unknown")
    value = data.get("value", query_label)
    search_id = data.get("searchId", "")
    progress = data.get("progress")
    results = data.get("results") or []

    lines = [
        f"[Sherlockeye] Query: {value}",
        f"[Sherlockeye] Type: {search_type}",
        f"[Sherlockeye] Status: {status}",
    ]
    if search_id:
        lines.append(f"[Sherlockeye] Search ID: {search_id}")
    if progress is not None:
        lines.append(f"[Sherlockeye] Progress: {progress}%")

    if status in ("failed",):
        lines.append("[Sherlockeye] Search failed — no results returned.")
        return "\n".join(lines)

    if not results:
        if status in ("processing",):
            lines.append(
                "[Sherlockeye] Search still processing — try again later or increase timeout."
            )
        else:
            lines.append("[Sherlockeye] No results found.")
        return "\n".join(lines)

    lines.append(f"\n[Sherlockeye] Results ({len(results)} item(s)):")
    for idx, item in enumerate(results[:_MAX_RESULTS_DISPLAY], start=1):
        if isinstance(item, dict):
            lines.extend(_format_result_item(item, idx))
    if len(results) > _MAX_RESULTS_DISPLAY:
        lines.append(f"  … and {len(results) - _MAX_RESULTS_DISPLAY} more result(s) truncated.")
    return "\n".join(lines)


async def _create_sync_search(
    session: aiohttp.ClientSession,
    payload: dict,
) -> dict:
    response = await _api_request(session, "POST", "/v1/searches/sync", json_payload=payload)
    return response.get("data", {})


async def _create_async_search(
    session: aiohttp.ClientSession,
    payload: dict,
) -> dict:
    response = await _api_request(session, "POST", "/v1/searches", json_payload=payload)
    return response.get("data", {})


async def _get_search(session: aiohttp.ClientSession, search_id: str) -> dict:
    response = await _api_request(session, "GET", f"/v1/searches/{search_id}")
    return response.get("data", {})


async def _poll_until_done(
    session: aiohttp.ClientSession,
    search_id: str,
    deadline: float,
) -> dict:
    while True:
        data = await _get_search(session, search_id)
        status = (data.get("status") or "").lower()
        if status in _TERMINAL_STATUSES:
            return data
        if asyncio.get_running_loop().time() >= deadline:
            return data
        await asyncio.sleep(_POLL_INTERVAL)


async def run_sherlockeye_osint(
    query: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
    deep_research: bool = False,
) -> str:
    """
    Run a Sherlockeye reverse OSINT search for *query*.

  Parameters
    ----------
    query
        Plain value (type inferred) or explicit ``type:"value"`` / ``type:value``.
    timeout_seconds
        Maximum wait time for sync search and polling fallback.
    deep_research
        When True, enables ``digital_accounts_expansion`` for email/phone/name.
    """
    api_key = os.environ.get("SHERLOCKEYE_API_KEY", "")
    if not api_key:
        return _MISSING_KEY_ERROR

    try:
        search_type, value = _parse_query(query)
    except ValueError as exc:
        return f"Scan error: {exc}"

    payload: dict = {"type": search_type, "value": value, "timeoutSeconds": timeout_seconds}
    if deep_research:
        payload["additional_modules"] = ["digital_accounts_expansion"]

    timeout_cfg = aiohttp.ClientTimeout(total=timeout_seconds + 30)
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    try:
        async with aiohttp.ClientSession(
            headers=_build_headers(api_key),
            timeout=timeout_cfg,
        ) as session:
            data = await _create_sync_search(session, payload)
            status = (data.get("status") or "").lower()

            if status == "processing" and data.get("searchId"):
                data = await _poll_until_done(session, data["searchId"], deadline)

            if status == "processing" and not data.get("results"):
                async_payload = {k: v for k, v in payload.items() if k != "timeoutSeconds"}
                created = await _create_async_search(session, async_payload)
                search_id = created.get("searchId")
                if search_id:
                    data = await _poll_until_done(session, search_id, deadline)

            return _format_search_response(data, query)

    except asyncio.TimeoutError:
        return f"Scan error: Sherlockeye request timed out after {timeout_seconds}s."
    except aiohttp.ClientError as exc:
        return f"Scan error: Network error querying Sherlockeye: {exc}"
    except ValueError as exc:
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during Sherlockeye lookup.")
        return f"Internal error: {exc}"
