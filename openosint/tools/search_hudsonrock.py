# openosint/tools/search_hudsonrock.py
"""
Hudson Rock infostealer-corpus intelligence (community tier).

Queries Hudson Rock's Cavalier API for credentials exposed via infostealer
malware (RedLine, Raccoon, Vidar, Lumma, StealC, …). Free public endpoint,
no API key, 50 req / 10 s rate limit.

Auto-routes by input shape:
  - email   (contains '@.')           → /search-by-email
  - domain  (dotted, alpha TLD)        → /search-by-domain
  - phone / username (everything else) → /search-by-username
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Literal

import aiohttp

logger = logging.getLogger(__name__)

_BASE_URL = "https://cavalier.hudsonrock.com/api/json/v2/osint-tools"
_DEFAULT_TIMEOUT = 30

_ENDPOINTS = {
    "email": "/search-by-email",
    "domain": "/search-by-domain",
    "username": "/search-by-username",
}
_PARAM_KEYS = {"email": "email", "domain": "domain", "username": "username"}

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w.-]+\.[a-z]{2,}$", re.IGNORECASE)
_PHONE_BODY_RE = re.compile(r"^[\d\- ]+$")
_DOMAIN_TLD_RE = re.compile(r"^[a-z]{2,}$", re.IGNORECASE)

Kind = Literal["email", "domain", "username"]


def _classify(query: str) -> Kind:
    q = query.strip()
    if "@" in q:
        return "email"
    if q.startswith("+") and _PHONE_BODY_RE.match(q[1:] or ""):
        return "username"
    if "." in q and " " not in q:
        last = q.rsplit(".", 1)[1]
        if _DOMAIN_TLD_RE.match(last):
            return "domain"
    return "username"


def _is_valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value.strip()))


def _raise_for_status(status: int) -> None:
    if status == 429:
        raise ValueError("Hudson Rock: rate limit exceeded (50 req / 10s).")
    if status != 200:
        raise ValueError(f"Hudson Rock returned HTTP {status}.")


async def _fetch_hudsonrock(
    endpoint: str,
    param_key: str,
    value: str,
    timeout: int,
    api_key: str = "",
) -> dict:
    url = f"{_BASE_URL}{endpoint}"
    params = {param_key: value}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
        async with session.get(url, params=params, headers=headers) as resp:
            if resp.status == 404:
                return {}
            _raise_for_status(resp.status)
            return await resp.json()


def _format_domain(query: str, data: dict) -> str:
    total_stealers = data.get("totalStealers", 0) or 0
    employees = data.get("employees", 0) or 0
    users = data.get("users", 0) or 0
    third_parties = data.get("third_parties", 0) or 0

    if not (total_stealers or employees or users):
        return f"[HudsonRock] No infostealer-compromised credentials found for {query}."

    lines = [
        "[HudsonRock] Query type: domain",
        f"[HudsonRock] Target: {query}",
        f"[HudsonRock] Total stealers seen: {total_stealers:,}",
        f"[HudsonRock] Compromised employees: {employees:,}",
        f"[HudsonRock] Compromised users: {users:,}",
        f"[HudsonRock] Third-party exposures: {third_parties:,}",
    ]
    if data.get("last_employee_compromised"):
        lines.append(f"[HudsonRock] Last employee compromised: {data['last_employee_compromised']}")
    if data.get("last_user_compromised"):
        lines.append(f"[HudsonRock] Last user compromised: {data['last_user_compromised']}")

    families = data.get("stealerFamilies") or {}
    if isinstance(families, dict) and families:
        named = [
            (k, v) for k, v in families.items() if k != "total" and isinstance(v, (int, float))
        ]
        top = sorted(named, key=lambda kv: kv[1], reverse=True)[:5]
        if top:
            lines.append(
                "[HudsonRock] Top stealer families: "
                + ", ".join(f"{name} ({count:,})" for name, count in top)
            )

    antiviruses = ((data.get("antiviruses") or {}).get("list")) or []
    if isinstance(antiviruses, list) and antiviruses:
        top_av = sorted(
            (a for a in antiviruses if isinstance(a, dict)),
            key=lambda a: a.get("count", 0),
            reverse=True,
        )[:3]
        if top_av:
            lines.append(
                "[HudsonRock] Top AVs on victims: "
                + ", ".join(f"{a.get('name', '?')} ({a.get('count', 0)})" for a in top_av)
            )

    lines.append("⚠️  COMPROMISED — credentials present in infostealer corpus")
    return "\n".join(lines)


def _format_stealers(kind: Kind, query: str, data: dict) -> str:
    stealers = data.get("stealers") or []
    if not isinstance(stealers, list) or not stealers:
        return f"[HudsonRock] No infostealer-compromised credentials found for {query}."

    corp = data.get("total_corporate_services", 0) or 0
    user = data.get("total_user_services", 0) or 0

    lines = [
        f"[HudsonRock] Query type: {kind}",
        f"[HudsonRock] Target: {query}",
        f"[HudsonRock] Stealer records: {len(stealers)}",
        f"[HudsonRock] Corporate services exposed: {corp}",
        f"[HudsonRock] User services exposed: {user}",
    ]

    for i, s in enumerate(stealers[:3], 1):
        if not isinstance(s, dict):
            continue
        lines.append(f"[HudsonRock] --- Record {i} ---")
        if s.get("date_compromised"):
            lines.append(f"[HudsonRock]   Date compromised: {s['date_compromised']}")
        if s.get("computer_name"):
            lines.append(f"[HudsonRock]   Computer name: {s['computer_name']}")
        if s.get("operating_system"):
            lines.append(f"[HudsonRock]   OS: {s['operating_system']}")
        if s.get("ip"):
            lines.append(f"[HudsonRock]   IP (masked): {s['ip']}")
        avs = s.get("antiviruses")
        if isinstance(avs, list) and avs:
            lines.append(f"[HudsonRock]   AVs on machine: {', '.join(str(a) for a in avs)}")
        logins = s.get("top_logins")
        if isinstance(logins, list) and logins:
            lines.append(
                f"[HudsonRock]   Top logins (redacted): {', '.join(str(x) for x in logins[:3])}"
            )

    if len(stealers) > 3:
        lines.append(f"[HudsonRock] ... {len(stealers) - 3} more record(s) omitted")

    lines.append("⚠️  COMPROMISED — credentials present in infostealer corpus")
    return "\n".join(lines)


def _format_results(kind: Kind, query: str, data: dict) -> str:
    if kind == "domain":
        return _format_domain(query, data)
    return _format_stealers(kind, query, data)


async def run_hudsonrock_osint(
    query: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
) -> str:
    """Search Hudson Rock's Cavalier infostealer corpus.

    The free public endpoint requires no API key. ``HUDSONROCK_API_KEY``, if set,
    is sent as ``Authorization: Bearer <key>`` for commercial-tier access.
    """
    q = query.strip()
    if not q:
        return "Invalid query: empty input."

    kind = _classify(q)

    if kind == "email" and not _is_valid_email(q):
        return "Invalid query: malformed email address."

    api_key = os.environ.get("HUDSONROCK_API_KEY", "").strip()

    try:
        payload = await _fetch_hudsonrock(
            _ENDPOINTS[kind],
            _PARAM_KEYS[kind],
            q,
            timeout_seconds,
            api_key=api_key,
        )
        return _format_results(kind, q, payload)
    except asyncio.TimeoutError:
        return f"Scan error: Hudson Rock request timed out after {timeout_seconds}s."
    except aiohttp.ClientError as exc:
        return f"Scan error: Network error querying Hudson Rock: {exc}"
    except ValueError as exc:
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during Hudson Rock lookup.")
        return f"Internal error: {exc}"
