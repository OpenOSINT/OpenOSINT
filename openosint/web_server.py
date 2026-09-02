# openosint/web_server.py
"""
OpenOSINT Web Server — FastAPI REST + SSE backend.

Routes:
  GET  /                       serve web/index.html
  GET  /api/health             version + setup status
  GET  /api/tools              tool catalog with availability
  POST /api/run/{tool_name}    run tool, return full result
  GET  /api/stream/{tool_name} stream output via Server-Sent Events
  POST /api/chat               AI chat with tool_use (SSE)
  POST /api/setup              save API keys to .env (localhost only)
  GET  /docs/*                 docs/ static files (mounted)
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import socket
import time
from collections import OrderedDict
from collections import deque as _deque
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlparse as _urlparse

import requests as _requests
from dotenv import load_dotenv

try:
    import httpx as _httpx
except ImportError:
    _httpx = None  # type: ignore

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from sse_starlette.sse import EventSourceResponse

from openosint.brightdata import BRIGHTDATA_LINK_WEB
from openosint.tools.generate_dorks import run_dork_osint
from openosint.tools.scrape_url import run_scrape_url_osint
from openosint.tools.search_abuseipdb import run_abuseipdb_osint
from openosint.tools.search_breach import run_breach_osint
from openosint.tools.search_censys import run_censys_osint
from openosint.tools.search_dns import run_dns_osint
from openosint.tools.search_domain import run_domain_osint
from openosint.tools.search_dorks_live import run_dorks_live_osint
from openosint.tools.search_email import run_email_osint
from openosint.tools.search_footprint import run_footprint_osint
from openosint.tools.search_gdelt_geo import run_gdelt_geo_osint, split_geojson_fence
from openosint.tools.search_github import run_github_osint
from openosint.tools.search_ip import run_ip_osint
from openosint.tools.search_ip2location import run_ip2location_osint
from openosint.tools.search_paste import run_paste_osint
from openosint.tools.search_phone import run_phone_osint
from openosint.tools.search_shodan import run_shodan_osint
from openosint.tools.search_username import run_username_osint
from openosint.tools.search_virustotal import run_virustotal_osint
from openosint.tools.search_whois import run_whois_osint
from openosint import __version__ as _VERSION
from openosint.regexes import EMAIL_FIND_RE
_ROOT = Path(__file__).parent.parent

# Web assets: prefer the package-relative path (pip install) with project-root fallback (dev/editable)
_PACKAGE_WEB = Path(__file__).parent / "web"
_WEB_DIR = _PACKAGE_WEB if _PACKAGE_WEB.exists() else _ROOT / "web"

load_dotenv()

# ---------------------------------------------------------------------------
# Demo mode / proxy / CORS config
# ---------------------------------------------------------------------------

# When True: no DB writes, no analytics.  api_keys are never logged regardless.
#
# DEMO_MODE is a network-exposure invariant, not an opt-in flag: whether a
# locally-held provider key (an operator's, or a self-hoster's own) may be
# used to serve a request depends on whether this process is reachable from
# anywhere but the machine it's running on — not on whether anyone remembered
# to set an env var. A self-hosted install bound to loopback with keys in its
# own .env is normal operation and gets no restriction, env var or not. A
# process bound to any other interface — including one we can't identify as
# loopback — never uses a locally-held key to serve a request; callers supply
# their own, or the tool is unavailable. See .claude/LEGAL_CONTEXT.md §8 and
# legal/INCIDENT-NOTES.md for why this replaced an env-var-only gate.
_SAFE_BIND_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_loopback_host(host: str | None) -> bool:
    """True only for an exact, known loopback address.

    None (bind address undeterminable — e.g. `create_app()` invoked directly
    as a uvicorn --factory target, bypassing serve_async()/run_server()) or
    anything else, including "0.0.0.0" or a real interface IP, is NOT
    loopback. Ambiguity fails closed to "not loopback" — see module note above.
    """
    return host is not None and host.strip() in _SAFE_BIND_HOSTS


def _env_forces_demo_mode() -> bool:
    """OPENOSINT_DEMO_MODE can only ADD restriction, never remove it.

    A non-loopback bind is always restricted regardless of this var — that
    safety no longer depends on anyone setting it. A recognized true-ish
    value forces restriction even on loopback (e.g. to rehearse demo
    behavior locally). Anything else — unset, malformed, or an explicit
    false-ish value — adds no restriction of its own.
    """
    return os.getenv("OPENOSINT_DEMO_MODE", "").strip().lower() in ("1", "true", "yes", "on")


def _compute_demo_mode(host: str | None) -> bool:
    """The network-exposure invariant described above, as a pure function of
    the bind address (plus the tighten-only env override)."""
    return (not _is_loopback_host(host)) or _env_forces_demo_mode()


# Set for real by create_app(host=...) before routes are built; None here
# means "undetermined" until then, which _compute_demo_mode treats as
# not-loopback (restricted) — see _is_loopback_host.
DEMO_MODE: bool = _compute_demo_mode(None)

# Trust CF-Connecting-IP / X-Forwarded-For for rate limiting only when
# explicitly enabled — prevents IP spoofing in local dev.
TRUSTED_PROXY: bool = os.getenv("TRUSTED_PROXY", "").lower() in ("1", "true", "yes")

# Deliberately NOT the same flag as TRUSTED_PROXY above. TRUSTED_PROXY only
# changes which IP string gets attributed to a request for rate-limit
# bucketing — a wrong value there means someone's rate limit resets a bit
# early or late. This flag gates whether a locally-held provider key may be
# used at all, the same invariant DEMO_MODE enforces for bind address. Those
# are different stakes: an operator who set TRUSTED_PROXY=true purely to get
# correct rate-limit IPs never consented to that also unlocking credentialed
# access for anyone the proxy relays, so it gets its own explicit opt-in.
# See the README's deployment-guidance section.
OPENOSINT_TRUSTED_PROXY: bool = os.getenv("OPENOSINT_TRUSTED_PROXY", "").strip().lower() in (
    "1", "true", "yes", "on",
)

# Headers whose mere presence means "a proxy sits in front of this
# connection" — GHSA-cqr4-hcfp-m6m4's exact concern, extended from
# /api/setup (_is_loopback_request above) to every credentialed-tool and
# chat gate. Content is never trusted for identity (see
# _get_client_ip's TRUSTED_PROXY-gated use for that); only presence is used
# here, to decide whether a loopback bind can still be assumed private.
_FORWARDING_HEADER_NAMES: tuple[str, ...] = (
    "x-forwarded-for", "x-forwarded-proto", "x-forwarded-host", "forwarded", "cf-connecting-ip",
)

_FORWARDED_PARAM_RE = re.compile(r'(proto|host)="?([^;,"\s]+)"?', re.IGNORECASE)


def _request_carries_forwarding_signals(request: "Request") -> bool:
    """True if this request looks like it was relayed by a reverse proxy.

    A loopback bind means the OS only accepted this TCP connection from the
    same machine — but an on-host or sidecar proxy relaying a public request
    looks identical at that layer. Any of these headers is the signal that
    distinguishes "actually private" from "looks private because nothing
    terminates in front of it but a proxy that does." X-Forwarded-Host is
    the "proxy-set host that differs from the bind" case specifically — a
    proxy typically rewrites the raw Host header to its own upstream target
    and preserves the original request's host in this header instead, so
    the raw Host header itself is not a reliable signal (a test harness or
    a client's own choice of hostname varies it for reasons having nothing
    to do with proxying) and is deliberately not checked here.
    """
    headers = request.headers
    return any(headers.get(name) for name in _FORWARDING_HEADER_NAMES)


def _forwarding_headers_look_inconsistent(request: "Request") -> bool:
    """True if a forwarding header disagrees with itself — more than one
    distinct scheme/host value where a single trusted hop would add exactly
    one. This is checked regardless of OPENOSINT_TRUSTED_PROXY: declaring
    trust in a proxy is not the same as trusting headers that contradict
    each other, and a forwarding header may only ever add restriction,
    never remove it.
    """
    for header_name in ("x-forwarded-proto", "x-forwarded-host"):
        values = {v.strip().lower() for v in request.headers.get(header_name, "").split(",") if v.strip()}
        if len(values) > 1:
            return True
    forwarded = request.headers.get("forwarded", "")
    if forwarded:
        by_param: dict[str, set[str]] = {}
        for param, value in _FORWARDED_PARAM_RE.findall(forwarded):
            by_param.setdefault(param.lower(), set()).add(value.lower())
        if any(len(values) > 1 for values in by_param.values()):
            return True
    return False


_proxy_warning_emitted = False


def _request_restriction(request: "Request") -> tuple[bool, str]:
    """Whether THIS request must be treated as demo-restricted, and why.

    DEMO_MODE (bind address, computed once at startup) is the static floor —
    never loosened here. On top of it: a loopback bind can still be reached
    through an on-host reverse proxy, so a request carrying forwarding
    signals is treated as public unless OPENOSINT_TRUSTED_PROXY is declared,
    and internally inconsistent forwarding headers are treated as public
    even then. The reason is returned so the caller sees why, rather than a
    silent, unexplained restriction.
    """
    if DEMO_MODE:
        return True, "this instance is not bound to loopback"
    if _forwarding_headers_look_inconsistent(request):
        return True, "forwarding headers on this request are internally inconsistent"
    if _request_carries_forwarding_signals(request):
        global _proxy_warning_emitted
        if not OPENOSINT_TRUSTED_PROXY:
            if not _proxy_warning_emitted:
                _proxy_warning_emitted = True
                logging.getLogger(__name__).warning(
                    "Bound to loopback but received a request carrying proxy-forwarding "
                    "headers, with no OPENOSINT_TRUSTED_PROXY declared. If this instance is "
                    "served through a reverse proxy, it is reachable by others even though "
                    "it looks private from here — see the README's deployment-guidance "
                    "section before setting OPENOSINT_TRUSTED_PROXY=true."
                )
            return True, (
                "this request arrived carrying proxy-forwarding headers, but no trusted-proxy "
                "configuration is declared (set OPENOSINT_TRUSTED_PROXY=true only if this "
                "instance is deliberately served through a reverse proxy — see the README)"
            )
    return False, ""


_RAW_ORIGINS: str = os.getenv(
    "DEMO_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000"
)
_ALLOWED_ORIGINS: list[str] = [o.strip() for o in _RAW_ORIGINS.split(",") if o.strip()]

# ---------------------------------------------------------------------------
# In-process sliding-window rate limiter (keyless tools only)
# ---------------------------------------------------------------------------

_RATE_STORE: dict[str, "_deque[float]"] = {}
_MAX_IP_BUCKETS: int = int(os.getenv("RATE_LIMIT_MAX_IPS", "10000"))
_RL_WINDOW_SECS: float = float(os.getenv("RATE_LIMIT_WINDOW", "60"))
_RL_MAX_REQS: int = int(os.getenv("RATE_LIMIT_MAX", "30"))

# Tools that need no API key and are therefore cheaply spammable
_KEYLESS_TOOLS: frozenset[str] = frozenset(
    {"search_whois", "search_dns", "generate_dorks", "search_ip", "search_paste", "search_gdelt_geo"}
)

# ---------------------------------------------------------------------------
# Globe basemap tile proxy — GET /api/tiles/{z}/{x}/{y}.
#
# The browser never talks to EOX (or any CDN) directly: this app fetches the
# tile server-side and streams it back, same "zero third-party requests"
# invariant as the vendored Alpine/Tailwind/Cytoscape/MapLibre assets. Tiles
# are a fixed, historical (2020) imagery composite — they never change — so
# an in-process cache with no TTL is correct, just size-bounded.
# ponytail: single-process LRU dict; move to a real cache if this ever runs
# behind multiple worker processes.
_EOX_TILE_URL = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg"
_TILE_CACHE_MAX = 2000
_TILE_CACHE_CONTROL = "public, max-age=31536000, immutable"
# 4^z tiles per zoom level — hard cost ceiling, matches maxzoom on the
# client's raster source (see globe-renderer.js _style()). z7 is plenty for
# situational awareness; the client over-zooms z7 tiles past that.
_TILE_MAX_ZOOM = 7
_TILE_RATE_STORE: dict[str, "_deque[float]"] = {}
_TILE_RL_MAX_REQS: int = int(os.getenv("RATE_LIMIT_MAX_TILES", "300"))
_tile_cache: "OrderedDict[tuple[int, int, int], bytes]" = OrderedDict()
# 1x1 transparent GIF — served on any upstream failure so MapLibre shows a
# blank tile instead of a broken-image icon, and never retries in a loop.
_BLANK_TILE = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)


def _tile_cache_get(key: tuple[int, int, int]) -> bytes | None:
    value = _tile_cache.get(key)
    if value is not None:
        _tile_cache.move_to_end(key)
    return value


def _tile_cache_set(key: tuple[int, int, int], value: bytes) -> None:
    _tile_cache[key] = value
    _tile_cache.move_to_end(key)
    if len(_tile_cache) > _TILE_CACHE_MAX:
        _tile_cache.popitem(last=False)


_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1"})


def _is_loopback_request(request: "Request") -> bool:
    """True only for connections that actually terminate on this host.

    Deliberately ignores X-Forwarded-For / CF-Connecting-IP — those are
    attacker-controlled headers. GHSA-cqr4-hcfp-m6m4: /api/setup writes to
    live process env vars, so it must not trust proxy headers the way the
    keyless-tool rate limiter does.
    """
    return bool(request.client) and request.client.host in _LOOPBACK_HOSTS


def _setup_request_is_authorized(request: "Request") -> bool:
    """Gate for /api/setup that does not depend on network topology.

    request.client.host reflects whatever peer terminates the TCP connection
    to this process — on a PaaS like Heroku that's the platform's router, a
    distinct network peer, not loopback. That's the normal case and it's
    already rejected below. But this must not be the *only* line of defense:
    a future deploy behind an on-host reverse proxy (nginx sidecar, buildpack,
    etc.) would make the router's connection look like loopback and silently
    reopen GHSA-cqr4-hcfp-m6m4. So a loopback caller is always allowed (the
    single-user local CLI case), and a non-loopback caller is allowed only if
    it presents a token matching OPENOSINT_SETUP_TOKEN — which is unset by
    default, so remote /api/setup is off unless an operator opts in.
    """
    if _is_loopback_request(request):
        return True
    expected = os.environ.get("OPENOSINT_SETUP_TOKEN", "").strip()
    if not expected:
        return False
    supplied = request.headers.get("X-Setup-Token", "")
    return secrets.compare_digest(supplied, expected)


def _get_client_ip(request: "Request") -> str:
    """Return the real client IP, honouring proxy headers only when TRUSTED_PROXY is set."""
    if TRUSTED_PROXY:
        cf = request.headers.get("CF-Connecting-IP", "").strip()
        if cf:
            return cf
        xff = request.headers.get("X-Forwarded-For", "").strip()
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _sliding_window_allow(
    store: dict[str, "_deque[float]"], ip: str, max_reqs: int, window_secs: float, max_ip_buckets: int
) -> bool:
    """Sliding-window rate limiter over an arbitrary per-caller bucket store.
    Returns True when the request is allowed."""
    now = time.monotonic()

    # Slide the window and evict empty bucket
    if ip in store:
        q = store[ip]
        while q and now - q[0] > window_secs:
            q.popleft()
        if not q:
            del store[ip]

    # Enforce total bucket cap before inserting a new IP
    if ip not in store and len(store) >= max_ip_buckets:
        # Prefer evicting an already-expired bucket; fall back to oldest-inserted
        evicted = False
        for k, q in list(store.items()):
            if not q or now - q[0] > window_secs:
                del store[k]
                evicted = True
                break
        if not evicted:
            del store[next(iter(store))]

    q = store.setdefault(ip, _deque())
    if len(q) >= max_reqs:
        return False
    q.append(now)
    return True


def _check_rate_limit(ip: str) -> bool:
    """Sliding-window rate limiter for keyless OSINT tools."""
    return _sliding_window_allow(_RATE_STORE, ip, _RL_MAX_REQS, _RL_WINDOW_SECS, _MAX_IP_BUCKETS)


def _check_tile_rate_limit(ip: str) -> bool:
    """Sliding-window rate limiter for the globe tile proxy.

    A SEPARATE bucket from _check_rate_limit's _RATE_STORE — panning the
    globe burns through many tile requests per session, and must never be
    able to 429 an unrelated keyless tool call (e.g. search_ip) sharing the
    same client IP, or vice versa.
    """
    return _sliding_window_allow(_TILE_RATE_STORE, ip, _TILE_RL_MAX_REQS, _RL_WINDOW_SECS, _MAX_IP_BUCKETS)


# ---------------------------------------------------------------------------
# Tool catalog — drives both the REST API and the frontend sidebar
# ---------------------------------------------------------------------------

_TOOL_CATALOG: list[dict] = [
    # ---- Identity ----
    {
        "name": "search_email",
        "description": "Enumerate accounts linked to an email via holehe.",
        "input_label": "Email address",
        "input_placeholder": "target@example.com",
        "category": "Identity",
        "icon": "📧",
        "tool_type": "B",
        "requires_binary": ["holehe"],
        "requires_env": [],
        "binary_hints": {"holehe": "pip install holehe"},
    },
    {
        "name": "search_username",
        "description": "Enumerate platforms where a username is registered via sherlock.",
        "input_label": "Username",
        "input_placeholder": "johndoe99",
        "category": "Identity",
        "icon": "👤",
        "tool_type": "B",
        "requires_binary": ["sherlock"],
        "requires_env": [],
        "binary_hints": {"sherlock": "pip install sherlock-project"},
    },
    {
        "name": "search_breach",
        "description": "Check if an email appears in data breaches via HaveIBeenPwned.",
        "input_label": "Email address",
        "input_placeholder": "target@example.com",
        "category": "Identity",
        "icon": "🔓",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": ["HIBP_API_KEY"],
        "env_hints": {"HIBP_API_KEY": "haveibeenpwned.com/API/Key"},
    },
    # ---- Network ----
    {
        "name": "search_ip",
        "description": "Retrieve geolocation and ASN data for an IP address via ipinfo.io.",
        "input_label": "IP address",
        "input_placeholder": "8.8.8.8",
        "category": "Network",
        "icon": "🌐",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": [],
    },
    {
        "name": "search_whois",
        "description": "Retrieve WHOIS registration data for a domain.",
        "input_label": "Domain",
        "input_placeholder": "example.com",
        "category": "Network",
        "icon": "🔍",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": [],
    },
    {
        "name": "search_domain",
        "description": "Enumerate subdomains of a target domain via sublist3r.",
        "input_label": "Domain",
        "input_placeholder": "example.com",
        "category": "Network",
        "icon": "🗺️",
        "tool_type": "B",
        "requires_binary": ["sublist3r"],
        "requires_env": [],
        "binary_hints": {"sublist3r": "pip install sublist3r"},
    },
    {
        "name": "search_ip2location",
        "description": "Enhanced IP intelligence: geolocation, ISP, VPN/Proxy/Tor detection.",
        "input_label": "IP address",
        "input_placeholder": "8.8.8.8",
        "category": "Network",
        "icon": "📍",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": ["IP2LOCATION_API_KEY"],
        "env_hints": {"IP2LOCATION_API_KEY": "ip2location.io/pricing"},
    },
    {
        "name": "search_dns",
        "description": "Enumerate DNS records (A/MX/NS/TXT/DMARC/DKIM) and flag email security misconfigurations.",
        "input_label": "Domain",
        "input_placeholder": "example.com",
        "category": "Network",
        "icon": "🗄️",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": [],
    },
    {
        "name": "search_abuseipdb",
        "description": "Check an IP against AbuseIPDB for abuse confidence score and report history.",
        "input_label": "IP address",
        "input_placeholder": "8.8.8.8",
        "category": "Network",
        "icon": "🚨",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": ["ABUSEIPDB_API_KEY"],
        "env_hints": {"ABUSEIPDB_API_KEY": "abuseipdb.com/account/api"},
    },
    {
        "name": "search_gdelt_geo",
        "description": "Search worldwide geolocated news coverage via the GDELT GEO 2.0 API.",
        "input_label": "Keywords",
        "input_placeholder": "ukraine war",
        "category": "Network",
        "icon": "🌍",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": [],
    },
    # ---- Recon ----
    {
        "name": "generate_dorks",
        "description": "Generate targeted Google dork URLs for any target.",
        "input_label": "Target (name, email, username, domain)",
        "input_placeholder": "john doe",
        "category": "Recon",
        "icon": "🔎",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": [],
    },
    {
        "name": "search_paste",
        "description": "Search Pastebin dumps for an email or username via psbdmp.ws.",
        "input_label": "Email or username",
        "input_placeholder": "target@example.com",
        "category": "Recon",
        "icon": "📋",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": [],
    },
    {
        "name": "search_phone",
        "description": "Gather carrier and geolocation data for a phone number.",
        "input_label": "Phone number (E.164 format)",
        "input_placeholder": "+14155552671",
        "category": "Recon",
        "icon": "📱",
        "tool_type": "B",
        "requires_binary": ["phoneinfoga"],
        "requires_env": [],
        "binary_hints": {"phoneinfoga": "github.com/sundowndev/phoneinfoga/releases"},
    },
    {
        "name": "search_github",
        "description": "Search GitHub for a username, email, or keyword. Discovers profile, repos, and commit emails.",
        "input_label": "Username, email, or keyword",
        "input_placeholder": "johndoe99",
        "category": "Recon",
        "icon": "🐙",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": [],
        "env_hints": {"GITHUB_TOKEN": "github.com/settings/tokens (optional — raises rate limit)"},
    },
    {
        "name": "search_censys",
        "description": "Search Censys for internet-facing infrastructure data.",
        "input_label": "IP address or domain",
        "input_placeholder": "example.com",
        "category": "Recon",
        "icon": "🔭",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": ["CENSYS_API_ID", "CENSYS_SECRET"],
        "env_hints": {
            "CENSYS_API_ID": "search.censys.io/account",
            "CENSYS_SECRET": "search.censys.io/account",
        },
    },
    {
        "name": "search_shodan",
        "description": "Query Shodan for host intelligence or banner search.",
        "input_label": "IP address or search query",
        "input_placeholder": "8.8.8.8",
        "category": "Recon",
        "icon": "🛡️",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": ["SHODAN_API_KEY"],
        "env_hints": {"SHODAN_API_KEY": "account.shodan.io"},
    },
    {
        "name": "search_virustotal",
        "description": "Check IP, domain, URL, or file hash against VirusTotal.",
        "input_label": "IP, domain, URL, or file hash",
        "input_placeholder": "8.8.8.8",
        "category": "Recon",
        "icon": "🦠",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": ["VIRUSTOTAL_API_KEY"],
        "env_hints": {"VIRUSTOTAL_API_KEY": "virustotal.com/gui/my-apikey"},
    },
    {
        "name": "search_dorks_live",
        "description": (
            "Execute live Google dork searches via Bright Data SERP API. "
            "Returns structured results (title, URL, snippet) for each dork query."
        ),
        "input_label": "Target (name, email, username, domain)",
        "input_placeholder": "john doe",
        "category": "Recon",
        "icon": "🔎",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": ["BRIGHTDATA_API_KEY", "BRIGHTDATA_SERP_ZONE"],
        "env_hints": {
            "BRIGHTDATA_API_KEY": BRIGHTDATA_LINK_WEB,
            "BRIGHTDATA_SERP_ZONE": "Your Bright Data SERP zone name",
        },
    },
    {
        "name": "scrape_url",
        "description": (
            "Fetch any public URL via Bright Data Web Unlocker, bypassing Cloudflare/CAPTCHA. "
            "Returns clean Markdown."
        ),
        "input_label": "URL to fetch",
        "input_placeholder": "https://example.com",
        "category": "Recon",
        "icon": "🌍",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": ["BRIGHTDATA_API_KEY", "BRIGHTDATA_UNLOCKER_ZONE"],
        "env_hints": {
            "BRIGHTDATA_API_KEY": BRIGHTDATA_LINK_WEB,
            "BRIGHTDATA_UNLOCKER_ZONE": "Your Bright Data Web Unlocker zone name",
        },
    },
    {
        "name": "search_footprint",
        "description": (
            "Collect a target's public search-engine footprint via Bright Data SERP API. "
            "Detects entity type (email, username, domain, phone, or full name) and runs "
            "entity-type-aware Google queries, returning ECG nodes/edges for discovered profiles."
        ),
        "input_label": "Target (email, username, domain, phone, or full name)",
        "input_placeholder": "john doe",
        "category": "Recon",
        "icon": "👣",
        "tool_type": "A",
        "requires_binary": [],
        "requires_env": ["BRIGHTDATA_API_KEY", "BRIGHTDATA_SERP_ZONE"],
        "env_hints": {
            "BRIGHTDATA_API_KEY": BRIGHTDATA_LINK_WEB,
            "BRIGHTDATA_SERP_ZONE": "Your Bright Data SERP zone name",
        },
    },
]

# Map tool name → async callable(input_value: str, timeout: int, keys: dict) -> str
# keys is always passed (may be {}); each lambda extracts only the key(s) it needs.
_RUNNERS: dict[str, object] = {
    "search_email": lambda v, t, keys=None: run_email_osint(v, timeout_seconds=t),
    "search_username": lambda v, t, keys=None: run_username_osint(v, timeout_seconds=t),
    "search_breach": lambda v, t, keys=None: run_breach_osint(
        v, timeout_seconds=t, api_key=(keys or {}).get("HIBP_API_KEY")
    ),
    "search_whois": lambda v, t, keys=None: run_whois_osint(v, timeout_seconds=t),
    "search_ip": lambda v, t, keys=None: run_ip_osint(
        v, timeout_seconds=t, api_key=(keys or {}).get("IPINFO_TOKEN")
    ),
    "search_domain": lambda v, t, keys=None: run_domain_osint(v, timeout_seconds=t),
    "search_ip2location": lambda v, t, keys=None: run_ip2location_osint(
        v, timeout_seconds=t, api_key=(keys or {}).get("IP2LOCATION_API_KEY")
    ),
    "search_dns": lambda v, t, keys=None: run_dns_osint(v, timeout_seconds=t),
    "search_gdelt_geo": lambda v, t, keys=None: run_gdelt_geo_osint(v, timeout_seconds=t),
    "search_abuseipdb": lambda v, t, keys=None: run_abuseipdb_osint(
        v, timeout_seconds=t, api_key=(keys or {}).get("ABUSEIPDB_API_KEY")
    ),
    "generate_dorks": lambda v, _t, keys=None: run_dork_osint(v),
    "search_paste": lambda v, t, keys=None: run_paste_osint(v, timeout_seconds=t),
    "search_phone": lambda v, t, keys=None: run_phone_osint(v, timeout_seconds=t),
    "search_github": lambda v, t, keys=None: run_github_osint(
        v, timeout_seconds=t, api_key=(keys or {}).get("GITHUB_TOKEN")
    ),
    "search_shodan": lambda v, t, keys=None: run_shodan_osint(
        v, timeout_seconds=t, api_key=(keys or {}).get("SHODAN_API_KEY")
    ),
    "search_virustotal": lambda v, t, keys=None: run_virustotal_osint(
        v, timeout_seconds=t, api_key=(keys or {}).get("VIRUSTOTAL_API_KEY")
    ),
    "search_censys": lambda v, t, keys=None: run_censys_osint(
        v, timeout_seconds=t, api_keys=keys
    ),
    "search_dorks_live": lambda v, t, keys=None: run_dorks_live_osint(
        v, timeout_seconds=t, api_keys=keys
    ),
    "scrape_url": lambda v, t, keys=None: run_scrape_url_osint(
        v, timeout_seconds=t, api_keys=keys
    ),
    "search_footprint": lambda v, t, keys=None: run_footprint_osint(
        v, timeout_seconds=t, api_keys=keys
    ),
}

# Tools that run keyless (requires_env is empty — the catalog correctly says
# no key is required) but whose implementation still does
# `api_key or os.environ.get(ENV_VAR)` internally as an optional rate-limit
# boost. In demo mode this can't be gated by requires_env alone, or an
# operator key set on the server (now or in the future) would silently reach
# an anonymous caller's request. See run_tool()/stream_tool() demo-mode checks.
_OPTIONAL_OPERATOR_KEY_ENV: dict[str, str] = {
    "search_ip": "IPINFO_TOKEN",
    "search_github": "GITHUB_TOKEN",
}

# Claude tool schemas (one string "input" param per tool)
_CLAUDE_TOOLS: list[dict] = [
    {
        "name": meta["name"],
        "description": meta["description"],
        "input_schema": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": f"{meta['input_label']} — e.g. {meta['input_placeholder']}",
                }
            },
            "required": ["input"],
        },
    }
    for meta in _TOOL_CATALOG
]


def _check_available(meta: dict) -> tuple[bool, str | None]:
    """Return (is_available, reason_if_not) for a tool."""
    for binary in meta.get("requires_binary", []):
        if not shutil.which(binary):
            hint = meta.get("binary_hints", {}).get(binary, f"install {binary}")
            return False, f"{binary} not in PATH — {hint}"
    for key in meta.get("requires_env", []):
        if not os.environ.get(key, "").strip():
            hint = meta.get("env_hints", {}).get(key, "")
            suffix = f" — {hint}" if hint else ""
            return False, f"{key} not set{suffix}"
    return True, None


_KNOWN_ENV_KEYS = [
    "ANTHROPIC_API_KEY",
    "HIBP_API_KEY",
    "IPINFO_TOKEN",
    "IP2LOCATION_API_KEY",
    "CENSYS_API_ID",
    "CENSYS_SECRET",
    "SHODAN_API_KEY",
    "VIRUSTOTAL_API_KEY",
    "ABUSEIPDB_API_KEY",
    "GITHUB_TOKEN",
    "BRIGHTDATA_API_KEY",
    "BRIGHTDATA_SERP_ZONE",
    "BRIGHTDATA_UNLOCKER_ZONE",
]

# Keys /api/setup is allowed to write. Anything else in the request body is
# dropped — GHSA-cqr4-hcfp-m6m4 let a caller set arbitrary env vars (e.g.
# OPENAI_BASE_URL) this way, redirecting outbound chat traffic and its auth
# header to attacker infra.
_SETUP_ALLOWED_KEYS: frozenset[str] = frozenset(_KNOWN_ENV_KEYS) | {
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "OPENAI_API_KEY",
}

# Keys whose value must be a well-formed http(s) URL — prevents javascript:/
# file:/gopher: schemes or bare hostnames sneaking into a *_BASE_URL var that
# later gets used to build outbound requests.
_SETUP_URL_KEYS: frozenset[str] = frozenset({"OPENAI_BASE_URL"})


def _is_valid_base_url(value: str) -> bool:
    parsed = _urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _is_setup_complete() -> bool:
    if (_ROOT / ".env").exists():
        return True
    return any(os.environ.get(k, "").strip() for k in _KNOWN_ENV_KEYS)


# ---------------------------------------------------------------------------
# Client-supplied AI backend guards (GHSA-q6cw-g86h-m2cq)
#
# GHSA-cqr4-hcfp-m6m4 made /api/setup loopback-only, but /api/chat and
# /api/openai/test still accept openai_base_url + openai_api_key in the
# request body. If a caller supplies a base_url they control and leaves
# api_key blank, the old code filled api_key from os.environ — shipping the
# *server's* credential to the *attacker's* host. The fix is structural: a
# request-supplied destination and an environment-sourced credential must
# never be used together (see chat() / openai_test() below, which apply
# this to both endpoints identically). Everything here is gated behind
# OPENOSINT_ALLOW_CLIENT_BACKEND (off by default) — with it unset, a
# request-supplied base_url/host is rejected outright and the coupling
# never has a chance to happen.
# ---------------------------------------------------------------------------


def _byo_backend_enabled() -> bool:
    """OPENOSINT_ALLOW_CLIENT_BACKEND — off by default. Gates every request-
    supplied chat backend destination (openai_base_url, ollama_host)."""
    return os.environ.get("OPENOSINT_ALLOW_CLIENT_BACKEND", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _parse_csv_env(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


# Every rejection reachable from a client-supplied backend attempt — the
# flag being off, a malformed URL, a disallowed destination IP class, an
# unresolvable host, an OPENOSINT_ALLOWED_BASE_URLS mismatch, or a rejected
# browser origin — must produce this exact status + body. If any of these
# carried a distinct message, a prober could tell "the flag is off" apart
# from "the flag is on but this particular request was rejected", which is
# itself a leak of server configuration state (an oracle inside the oracle
# fix). The cost is a less specific error for legitimate self-hosters
# debugging their own setup — check server logs, not the HTTP response, to
# see which of these actually fired.
def _reject_client_backend() -> None:
    raise HTTPException(403, "client-supplied backend rejected")


async def _validate_outbound_base_url(url: str) -> str:
    """Validate a client-supplied backend base URL before it is used for an
    outbound request. Only ever called for request-supplied URLs — env-
    configured defaults (OPENAI_BASE_URL, the localhost:8080/11434 fallbacks)
    skip this entirely so they keep working unconditionally.

    Policy:
      * scheme must be http/https; no userinfo (user:pass@) in the URL.
      * OPENOSINT_ALLOWED_BASE_URLS, if set, is a strict per-host allowlist
        that overrides the IP checks below — an operator who has pinned
        trusted hosts has already accepted the DNS-rebinding risk knowingly.
      * Otherwise: link-local (169.254.0.0/16, fe80::/10 — cloud metadata,
        no legitimate use), multicast, IANA-reserved, and unspecified
        addresses are always rejected.
      * Loopback and RFC1918 are otherwise permitted — this function is only
        reached once OPENOSINT_ALLOW_CLIENT_BACKEND is set, and LAN Ollama /
        local llama.cpp users enabling that flag are exactly who needs them.

    Every failure path raises via _reject_client_backend() — see its
    docstring for why the message must not vary by reason.

    NOTE (TOCTOU): this resolves the hostname now, but the outbound HTTP
    client resolves it again when it actually connects — a DNS-rebinding
    attacker can swap the answer between the two lookups. Set
    OPENOSINT_ALLOWED_BASE_URLS to close this window; it pins a hostname,
    not a point-in-time IP.
    """
    parsed = _urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        _reject_client_backend()
    if not parsed.hostname:
        _reject_client_backend()
    if parsed.username or parsed.password:
        _reject_client_backend()

    allowlist = _parse_csv_env("OPENOSINT_ALLOWED_BASE_URLS")
    if allowlist:
        host = parsed.hostname.lower()
        host_port = f"{host}:{parsed.port}" if parsed.port else host
        allowed = {a.lower() for a in allowlist}
        if host not in allowed and host_port not in allowed:
            _reject_client_backend()
        return url

    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, None)
    except socket.gaierror:
        _reject_client_backend()

    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            _reject_client_backend()

    return url


def _check_browser_origin(request: "Request") -> None:
    """CSRF / DNS-rebinding guard for client-supplied-backend requests.

    Only called when OPENOSINT_ALLOW_CLIENT_BACKEND is set — see callers.
    This is NOT an authentication boundary: it only blocks a browser from
    being tricked into calling this endpoint cross-origin. A direct network
    attacker (no browser involved) is stopped by the credential/destination
    decoupling in _validate_outbound_base_url(), not by this check.

    curl, SDKs, and scripts send neither Sec-Fetch-Site nor Origin and are
    waved through deliberately — they are not a CSRF vector, and turning
    this into a general request allowlist would only break legitimate API
    consumers without adding real protection.

    Failures go through _reject_client_backend() too — this check only ever
    runs when the flag is on, so a distinct message here would itself
    confirm the flag is on to a cross-origin prober that never even sent a
    valid base_url.
    """
    sec_fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
    if sec_fetch_site:
        if sec_fetch_site not in ("same-origin", "none"):
            _reject_client_backend()
        return

    origin = request.headers.get("origin", "").strip()
    if origin:
        request_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
        allowed = {request_origin, *_parse_csv_env("OPENOSINT_ALLOWED_ORIGINS")}
        if origin not in allowed:
            _reject_client_backend()
        return

    # Neither header present: not a browser request (curl/SDK/script) — allow.


def _get_ai_backend() -> tuple[str, str | None, bool | None]:
    """Return (backend_name, ollama_host, ollama_reachable)."""
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "claude", None, None
    # An OpenAI-compatible endpoint (LiteLLM, llama-swap, vLLM, …) takes
    # precedence over Ollama when configured.
    if os.environ.get("OPENAI_BASE_URL", "").strip():
        return "openai", None, None
    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        resp = _requests.get(f"{ollama_host}/api/tags", timeout=2)
        reachable = resp.status_code == 200
    except Exception:
        reachable = False
    return ("ollama" if reachable else "none"), ollama_host, reachable


async def _probe_openai_endpoint(base_url: str, api_key: str) -> dict:
    """Probe an OpenAI-compatible endpoint server-side (no browser CORS / mixed-content).

    Distinguishes three states so the UI can give an accurate message:
      * unreachable      — connection failed / refused / timed out
      * reachable + auth_ok=False — server answered but rejected the key (401/403)
      * reachable + auth_ok=True  — server answered and accepted the key

    A 401/403 still means the endpoint is *up* and usable once a valid key is
    supplied, so we must not report it as "not configured / unreachable" — that
    was the old bug where a healthy LiteLLM/vLLM proxy showed as backend "none".
    """
    base = base_url.strip().rstrip("/")
    if not base:
        return {"reachable": False, "auth_ok": False, "status_code": None}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        if _httpx is not None:
            async with _httpx.AsyncClient(timeout=2.5, follow_redirects=False) as client:
                r = await client.get(f"{base}/models", headers=headers)
                status = r.status_code
        else:
            raw = await asyncio.to_thread(
                lambda: _requests.get(
                    f"{base}/models", headers=headers, timeout=2.5, allow_redirects=False
                )
            )
            status = raw.status_code
    except Exception:
        return {"reachable": False, "auth_ok": False, "status_code": None}
    return {
        "reachable": True,
        "auth_ok": status == 200,
        "status_code": status,
    }


class RunRequest(BaseModel):
    input: str
    timeout: int = 120
    api_keys: dict[str, str] | None = None  # per-request BYOK; never logged


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    model: str = "claude"
    ollama_model: str = "llama3.2"
    ollama_host: str = "http://localhost:11434"
    openai_base_url: str = ""
    openai_model: str = ""
    openai_api_key: str = ""


class OpenAITestRequest(BaseModel):
    """Body for POST /api/openai/test — all fields optional; blanks fall back
    to the server's OPENAI_BASE_URL / OPENAI_API_KEY env vars."""

    openai_base_url: str = ""
    openai_api_key: str = ""


class GraphDecideRequest(BaseModel):
    """Body for POST /api/graph/review/decide — a human verdict on one same_as pair."""

    entity_id: str
    canonical_id: str
    decision: str  # "accept" | "reject"
    reviewer_id: str | None = None


# The graph routes read only the local SQLite graph store. This is the single
# response every graph route returns when the optional `graph` extra
# (followthemoney) isn't installed, so the rest of the web UI keeps working.
def _graph_unavailable() -> JSONResponse:
    return JSONResponse(
        {
            "status": "error",
            "graph_available": False,
            "message": (
                "Graph features require the 'graph' extra. Install it with: "
                "pip install 'openosint[graph]'"
            ),
        },
        status_code=503,
    )


def _select_chat_backend(req: "ChatRequest") -> str:
    """Resolve which AI backend to use for a chat request: openai | ollama | claude."""
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    openai_base = (req.openai_base_url or os.environ.get("OPENAI_BASE_URL", "")).strip()

    # Explicit selection from the UI takes priority.
    if req.model == "openai":
        return "openai"
    if req.model == "ollama":
        return "ollama"
    if req.model == "claude" and has_anthropic:
        return "claude"

    # Auto-detect when no explicit, usable selection was made.
    if has_anthropic:
        return "claude"
    if openai_base:
        return "openai"
    if req.ollama_host:
        return "ollama"
    return "claude"


# ---------------------------------------------------------------------------
# AI chat streaming helpers
# ---------------------------------------------------------------------------


async def _run_tool(tool_name: str, tool_input: str, timeout: int = 120) -> str:
    if tool_name not in _RUNNERS:
        return f"Unknown tool: {tool_name}"
    if not str(tool_input).strip():
        return (
            f"Tool call error: 'input' is required for {tool_name} but was not provided. "
            "Retry with the target value as the 'input' parameter."
        )
    try:
        return await _RUNNERS[tool_name](tool_input, timeout)
    except Exception as exc:
        return f"Error: {exc}"


async def _stream_claude(messages: list[dict]) -> AsyncIterator[dict]:
    """Yield SSE event dicts while running an agentic Claude loop with tool_use."""
    try:
        import anthropic as _anthropic
    except ImportError:
        yield {
            "type": "error",
            "message": "anthropic package not installed. Run: pip install anthropic",
        }
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        yield {"type": "error", "message": "ANTHROPIC_API_KEY not set."}
        return

    client = _anthropic.AsyncAnthropic(api_key=api_key)
    msgs = list(messages)
    _MAX_TOOL_ROUNDS = 5
    _tool_rounds = 0

    system_prompt = (
        "You are OpenOSINT, an AI-powered OSINT investigation assistant. "
        "When the user asks you to investigate a target, use the available tools to gather intelligence. "
        "Summarize findings clearly and highlight anything suspicious or notable. "
        "Always clarify what tools you used and what each result means."
    )

    while True:
        _tool_rounds += 1
        if _tool_rounds > _MAX_TOOL_ROUNDS:
            yield {"type": "error", "message": "Tool call limit reached (5 rounds)."}
            return
        full_content: list[dict] = []
        pending_tool_results: list[dict] = []
        current_block: dict | None = None
        current_tool_json = ""
        stop_reason = "end_turn"

        try:
            async with client.messages.stream(
                model="claude-sonnet-4-5",
                max_tokens=4096,
                system=system_prompt,
                tools=_CLAUDE_TOOLS,
                messages=msgs,
            ) as stream:
                async for event in stream:
                    etype = event.type

                    if etype == "content_block_start":
                        cb = event.content_block
                        if cb.type == "text":
                            current_block = {"type": "text", "text": ""}
                            full_content.append(current_block)
                        elif cb.type == "tool_use":
                            current_block = {
                                "type": "tool_use",
                                "id": cb.id,
                                "name": cb.name,
                                "input": {},
                            }
                            current_tool_json = ""
                            full_content.append(current_block)

                    elif etype == "content_block_delta":
                        d = event.delta
                        if (
                            d.type == "text_delta"
                            and current_block
                            and current_block["type"] == "text"
                        ):
                            current_block["text"] += d.text
                            yield {"type": "text", "content": d.text}
                        elif d.type == "input_json_delta":
                            current_tool_json += d.partial_json

                    elif etype == "content_block_stop":
                        if current_block and current_block["type"] == "tool_use":
                            try:
                                input_data = (
                                    json.loads(current_tool_json) if current_tool_json else {}
                                )
                            except Exception:
                                input_data = {"input": current_tool_json}
                            current_block["input"] = input_data

                            tool_name = current_block["name"]
                            tool_input = input_data.get("input", "")
                            if not tool_input and input_data:
                                tool_input = next(
                                    (v for v in input_data.values() if isinstance(v, str)),
                                    str(input_data),
                                )

                            yield {
                                "type": "tool_start",
                                "tool": tool_name,
                                "input": str(tool_input),
                            }

                            t0 = time.monotonic()
                            result = await _run_tool(tool_name, str(tool_input))
                            elapsed = round(time.monotonic() - t0, 2)

                            yield {
                                "type": "tool_result",
                                "tool": tool_name,
                                "output": result,
                                "elapsed": elapsed,
                            }
                            # Provider gets the stripped text; every subsequent
                            # round resends the whole message list.
                            model_text, _ = split_geojson_fence(result)
                            pending_tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": current_block["id"],
                                    "content": model_text,
                                }
                            )

                        current_block = None
                        current_tool_json = ""

                final_msg = await stream.get_final_message()
                stop_reason = final_msg.stop_reason or "end_turn"

        except Exception as exc:
            yield {"type": "error", "message": str(exc)}
            return

        if stop_reason != "tool_use" or not pending_tool_results:
            break

        msgs = msgs + [
            {"role": "assistant", "content": full_content},
            {"role": "user", "content": pending_tool_results},
        ]

    yield {"type": "done"}


async def _stream_ollama(
    messages: list[dict], ollama_host: str, ollama_model: str
) -> AsyncIterator[dict]:
    """Yield SSE event dicts using Ollama chat API with tool_use."""
    host = ollama_host.rstrip("/")
    msgs = list(messages)

    ollama_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in _CLAUDE_TOOLS
    ]

    while True:
        try:
            payload = {
                "model": ollama_model,
                "messages": msgs,
                "tools": ollama_tools,
                "stream": False,
            }
            if _httpx is not None:
                async with _httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
                    r = await client.post(f"{host}/api/chat", json=payload)
                if r.status_code != 200:
                    yield {
                        "type": "error",
                        "message": f"Ollama returned HTTP {r.status_code}: {r.text[:200]}",
                    }
                    return
                data = r.json()
            else:
                # fallback: run blocking requests in a thread
                _payload = payload  # capture for lambda
                raw = await asyncio.to_thread(
                    lambda: _requests.post(
                        f"{host}/api/chat", json=_payload, timeout=120, allow_redirects=False
                    )
                )
                if raw.status_code != 200:
                    yield {
                        "type": "error",
                        "message": f"Ollama returned HTTP {raw.status_code}: {raw.text[:200]}",
                    }
                    return
                data = raw.json()
        except Exception as exc:
            yield {"type": "error", "message": f"Ollama request failed: {exc}"}
            return

        msg = data.get("message", {})
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        if content:
            yield {"type": "text", "content": content}

        if not tool_calls:
            break

        tool_results_for_next = []
        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            raw_args = fn.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except Exception:
                    raw_args = {"input": raw_args}
            tool_input = raw_args.get("input", "")
            if not tool_input and raw_args:
                tool_input = next(
                    (v for v in raw_args.values() if isinstance(v, str)), str(raw_args)
                )

            yield {"type": "tool_start", "tool": tool_name, "input": str(tool_input)}

            t0 = time.monotonic()
            result = await _run_tool(tool_name, str(tool_input))
            elapsed = round(time.monotonic() - t0, 2)

            yield {"type": "tool_result", "tool": tool_name, "output": result, "elapsed": elapsed}
            model_text, _ = split_geojson_fence(result)
            tool_results_for_next.append({"role": "tool", "content": model_text})

        msgs = (
            msgs
            + [{"role": "assistant", "content": content, "tool_calls": tool_calls}]
            + tool_results_for_next
        )

    yield {"type": "done"}


async def _stream_openai(
    messages: list[dict],
    base_url: str,
    api_key: str,
    model: str,
) -> AsyncIterator[dict]:
    """Yield SSE event dicts using any OpenAI-compatible chat-completions API."""
    base = base_url.rstrip("/")
    url = f"{base}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    msgs = list(messages)

    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in _CLAUDE_TOOLS
    ]

    while True:
        payload = {
            "model": model,
            "messages": msgs,
            "tools": openai_tools,
            "tool_choice": "auto",
            "stream": False,
        }
        try:
            if _httpx is not None:
                async with _httpx.AsyncClient(timeout=180, follow_redirects=False) as client:
                    r = await client.post(url, json=payload, headers=headers)
                if r.status_code != 200:
                    yield {
                        "type": "error",
                        "message": f"OpenAI endpoint returned HTTP {r.status_code}: {r.text[:300]}",
                    }
                    return
                data = r.json()
            else:
                _payload = payload  # capture for lambda
                raw = await asyncio.to_thread(
                    lambda: _requests.post(
                        url, json=_payload, headers=headers, timeout=180, allow_redirects=False
                    )
                )
                if raw.status_code != 200:
                    yield {
                        "type": "error",
                        "message": f"OpenAI endpoint returned HTTP {raw.status_code}: {raw.text[:300]}",
                    }
                    return
                data = raw.json()
        except Exception as exc:
            yield {"type": "error", "message": f"OpenAI request failed: {exc}"}
            return

        choices = data.get("choices") or []
        if not choices:
            yield {
                "type": "error",
                "message": f"OpenAI endpoint returned no choices: {str(data)[:300]}",
            }
            return
        msg = choices[0].get("message", {})
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        if content:
            yield {"type": "text", "content": content}

        if not tool_calls:
            break

        tool_results_for_next = []
        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            raw_args = fn.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except Exception:
                    raw_args = {"input": raw_args}
            tool_input = raw_args.get("input", "")
            if not tool_input and raw_args:
                tool_input = next(
                    (v for v in raw_args.values() if isinstance(v, str)), str(raw_args)
                )

            yield {"type": "tool_start", "tool": tool_name, "input": str(tool_input)}

            t0 = time.monotonic()
            result = await _run_tool(tool_name, str(tool_input))
            elapsed = round(time.monotonic() - t0, 2)

            yield {"type": "tool_result", "tool": tool_name, "output": result, "elapsed": elapsed}
            model_text, _ = split_geojson_fence(result)
            tool_results_for_next.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": model_text,
                }
            )

        msgs = (
            msgs
            + [{"role": "assistant", "content": content, "tool_calls": tool_calls}]
            + tool_results_for_next
        )

    yield {"type": "done"}


# ---------------------------------------------------------------------------
# Demo chat — pre-scripted SSE stream, no API key required
# ---------------------------------------------------------------------------


async def _demo_chat_stream(message: str) -> AsyncIterator[dict]:
    """Yield scripted SSE events that look like a real investigation."""

    async def stream_text(text: str) -> AsyncIterator[dict]:
        words = text.split(" ")
        for i, word in enumerate(words):
            chunk = word if i == len(words) - 1 else word + " "
            yield {"type": "text", "content": chunk}
            await asyncio.sleep(0.03)

    msg_lower = message.lower()

    # --- tools / availability query ---
    if any(kw in msg_lower for kw in ("tool", "available", "what can")):
        lines = [
            "I have **16 OSINT tools** available for investigations:\n\n",
            "**Identity:** `search_email`, `search_username`, `search_breach`\n\n",
            "**Network:** `search_ip`, `search_whois`, `search_domain`, `search_ip2location`, `search_abuseipdb`\n\n",
            "**Recon:** `generate_dorks`, `search_paste`, `search_phone`, `search_shodan`, `search_virustotal`, `search_censys`, `search_dns`, `search_github`\n\n",
            "Just give me a target — email address, username, domain, or IP.",
        ]
        for line in lines:
            async for event in stream_text(line):
                yield event
        yield {"type": "done"}
        return

    # --- email investigation ---
    email_match = EMAIL_FIND_RE.search(message)
    if email_match or any(kw in msg_lower for kw in ("email", "investigate", "@")):
        email = email_match.group(0) if email_match else "demo@example.com"
        async for event in stream_text(f"Investigating **{email}**...\n\n"):
            yield event

        yield {"type": "tool_start", "tool": "search_email", "input": email}
        await asyncio.sleep(1.5)
        yield {
            "type": "tool_result",
            "tool": "search_email",
            "output": (
                "[+] Spotify       https://open.spotify.com/user/demo\n"
                "[+] GitHub        https://github.com/demo\n"
                "[+] Gravatar      https://gravatar.com/demo\n"
                "[+] WordPress     https://wordpress.com/demo\n"
                "[*] Holehe scan complete — 4 accounts found"
            ),
            "elapsed": 1.4,
        }

        yield {"type": "tool_start", "tool": "search_breach", "input": email}
        await asyncio.sleep(1.2)
        yield {
            "type": "tool_result",
            "tool": "search_breach",
            "output": (
                "[!] LinkedIn (2016-05-17) — Passwords, Email addresses\n"
                "[!] Adobe (2013-10-04) — Passwords, Email addresses, Usernames\n"
                "[*] 2 breach(es) found via HaveIBeenPwned"
            ),
            "elapsed": 1.1,
        }

        summary = (
            f"## Summary\n\nTarget **{email}** has accounts on **4 platforms** "
            "and appears in **2 known data breaches** (LinkedIn 2016, Adobe 2013). "
            "Credential rotation strongly advised."
        )
        async for event in stream_text(summary):
            yield event
        yield {"type": "done"}
        return

    # --- IP investigation ---
    ip_match = re.search(r"\b(\d{1,3}\.){3}\d{1,3}\b", message)
    if ip_match or "ip" in msg_lower:
        ip = ip_match.group(0) if ip_match else "8.8.8.8"

        yield {"type": "tool_start", "tool": "search_ip", "input": ip}
        await asyncio.sleep(1.0)
        yield {
            "type": "tool_result",
            "tool": "search_ip",
            "output": (
                f"[+] IP: {ip}\n"
                "[+] Hostname: dns.google\n"
                "[+] Country: US — Mountain View, California\n"
                "[+] Org: AS15169 Google LLC\n"
                "[+] Timezone: America/Los_Angeles"
            ),
            "elapsed": 0.9,
        }

        yield {"type": "tool_start", "tool": "search_whois", "input": ip}
        await asyncio.sleep(0.8)
        yield {
            "type": "tool_result",
            "tool": "search_whois",
            "output": (
                "[+] IP Range: 8.8.8.0/24\n"
                "[+] Owner: Google LLC\n"
                "[+] Abuse: network-abuse@google.com\n"
                "[+] Country: US\n"
                "[+] Registered: 2014-03-14"
            ),
            "elapsed": 0.7,
        }

        summary = (
            f"**{ip}** is a Google public DNS server located in Mountain View, "
            "California. Owned by Google LLC (AS15169). No threat indicators found."
        )
        async for event in stream_text(summary):
            yield event
        yield {"type": "done"}
        return

    # --- default ---
    default_msg = (
        "I can help you investigate **emails**, **usernames**, **domains**, "
        "and **IP addresses** using 16 specialized OSINT tools. "
        "What would you like to look into?"
    )
    async for event in stream_text(default_msg):
        yield event
    yield {"type": "done"}


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(host: str | None = None) -> FastAPI:
    """Build the FastAPI app. `host` is the address this process will be
    bound to, if known — it decides the DEMO_MODE network-exposure invariant
    (see the module note near DEMO_MODE's definition). Leave it unset only
    when the bind address genuinely isn't known yet; that fails closed to
    restricted, not open."""
    global DEMO_MODE
    DEMO_MODE = _compute_demo_mode(host)

    app = FastAPI(
        title="OpenOSINT",
        version=_VERSION,
        docs_url=None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # GET /api/health
    # ------------------------------------------------------------------

    @app.get("/api/health")
    async def health(request: Request):
        ai_backend, ollama_host, ollama_reachable = _get_ai_backend()
        restricted, restriction_reason = _request_restriction(request)
        return {
            "status": "ok",
            "version": _VERSION,
            "demo_mode": DEMO_MODE,
            "restricted": restricted,
            "restriction_reason": restriction_reason or None,
            "setup_complete": _is_setup_complete(),
            "ai_backend": ai_backend,
            "ollama_host": ollama_host,
            "ollama_reachable": ollama_reachable,
        }

    # ------------------------------------------------------------------
    # GET /api/tools
    # ------------------------------------------------------------------

    @app.get("/api/tools")
    async def list_tools():
        result = []
        for meta in _TOOL_CATALOG:
            available, reason = _check_available(meta)
            result.append(
                {
                    "name": meta["name"],
                    "description": meta["description"],
                    "input_label": meta["input_label"],
                    "input_placeholder": meta["input_placeholder"],
                    "category": meta["category"],
                    "icon": meta.get("icon", ""),
                    "tool_type": meta.get("tool_type", "A"),
                    "required_keys": meta.get("requires_env", []),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input": {
                                "type": "string",
                                "description": meta["input_label"],
                                "example": meta["input_placeholder"],
                            }
                        },
                        "required": ["input"],
                    },
                    "available": available,
                    "unavailable_reason": reason,
                }
            )
        return result

    # ------------------------------------------------------------------
    # GET /api/sponsors
    # ------------------------------------------------------------------

    @app.get("/api/sponsors")
    async def list_sponsors():
        from openosint.sponsors import SponsorsValidationError, load_sponsors

        try:
            sponsors = load_sponsors()
        except SponsorsValidationError as exc:
            return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)
        return {"status": "ok", "sponsors": sponsors}

    # ------------------------------------------------------------------
    # GET /api/tiles/{z}/{x}/{y} — globe basemap tile proxy (see the
    # module-level comment near _tile_cache for why this exists).
    # ------------------------------------------------------------------

    @app.get("/api/tiles/{z}/{x}/{y}")
    async def get_tile(z: int, x: int, y: int, request: Request):
        if z < 0 or z > _TILE_MAX_ZOOM or x < 0 or x >= 2**z or y < 0 or y >= 2**z:
            return Response(status_code=404)

        cache_key = (z, x, y)
        cached = _tile_cache_get(cache_key)

        if cached is None:
            client_ip = _get_client_ip(request)
            if not _check_tile_rate_limit(client_ip):
                return Response(status_code=429)

            url = _EOX_TILE_URL.format(z=z, y=y, x=x)
            try:
                resp = await asyncio.to_thread(_requests.get, url, timeout=10)
            except Exception:
                logging.getLogger(__name__).warning("Tile fetch failed for z=%d x=%d y=%d", z, x, y)
                return Response(content=_BLANK_TILE, media_type="image/gif")

            if resp.status_code != 200:
                logging.getLogger(__name__).warning(
                    "Tile server returned HTTP %d for z=%d x=%d y=%d", resp.status_code, z, x, y
                )
                return Response(content=_BLANK_TILE, media_type="image/gif")

            cached = resp.content
            _tile_cache_set(cache_key, cached)

        # Imagery is a static 2020 composite — content-addressed ETag lets the
        # browser cache absorb repeat views instead of the in-process LRU.
        etag = f'"{hashlib.sha256(cached).hexdigest()[:16]}"'
        headers = {"Cache-Control": _TILE_CACHE_CONTROL, "ETag": etag}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)

        return Response(content=cached, media_type="image/jpeg", headers=headers)

    # ------------------------------------------------------------------
    # POST /api/run/{tool_name}
    # ------------------------------------------------------------------

    @app.post("/api/run/{tool_name}")
    async def run_tool(tool_name: str, req: RunRequest, request: Request):
        if tool_name not in _RUNNERS:
            return JSONResponse(
                {
                    "status": "error",
                    "output": f"Unknown tool: {tool_name}",
                    "tool": tool_name,
                    "elapsed": 0,
                },
                status_code=404,
            )

        # Rate-limit keyless tools per real client IP
        if tool_name in _KEYLESS_TOOLS:
            client_ip = _get_client_ip(request)
            if not _check_rate_limit(client_ip):
                return JSONResponse(
                    {
                        "status": "error",
                        "output": "Rate limit exceeded. Please wait before retrying.",
                        "tool": tool_name,
                        "elapsed": 0,
                    },
                    status_code=429,
                )

        restricted, restriction_reason = _request_restriction(request)

        # Breach data is never served from the operator's own key, BYOK or not —
        # this is a hard block with no flag, since the public-demo concern is
        # not just HIBP's ToS but the operator acting as controller for a
        # breach lookup on a non-consenting third party. See .claude/LEGAL_CONTEXT.md.
        if restricted and tool_name == "search_breach":
            return JSONResponse(
                {
                    "status": "error",
                    "output": "Breach-data lookups are disabled: " + restriction_reason,
                    "tool": tool_name,
                    "elapsed": 0,
                },
                status_code=403,
            )

        # Check that ALL required keys are present.
        # When restricted, the operator's own env var never counts — only a
        # caller-supplied key (BYOK) can satisfy a credentialed tool, so a
        # publicly-reachable instance can never run a lookup on a locally-held key.
        meta = next((m for m in _TOOL_CATALOG if m["name"] == tool_name), None)
        if meta:
            supplied: dict[str, str] = req.api_keys or {}
            if restricted:
                # search_ip/search_github work keyless (requires_env is empty
                # for both — the token only raises rate limits), but their
                # tool modules do `api_key or os.environ.get(...)` internally,
                # so a locally-held key would still leak through if we only
                # checked requires_env here. Gate them the same as a hard
                # requirement when restricted.
                demo_required_keys = set(meta.get("requires_env", []))
                optional_key = _OPTIONAL_OPERATOR_KEY_ENV.get(tool_name)
                if optional_key:
                    demo_required_keys.add(optional_key)
                missing = [k for k in sorted(demo_required_keys) if not supplied.get(k)]
            else:
                required_keys: list[str] = meta.get("requires_env", [])
                missing = [
                    k for k in required_keys
                    if not supplied.get(k) and not os.environ.get(k, "").strip()
                ]
            if missing:
                how_to_get = {k: meta.get("env_hints", {}).get(k, "") for k in missing}
                error_message = (
                    f"API key required — {restriction_reason}, so a locally-held key "
                    "cannot be used for this lookup. Pass your own key in the api_keys "
                    "field, or self-host with your own .env."
                    if restricted
                    else (
                        "API key required — pass it in the api_keys field "
                        "or set the corresponding environment variable"
                    )
                )
                return JSONResponse(
                    {
                        "status": "error",
                        "key_required": True,
                        "missing_keys": missing,
                        "how_to_get": how_to_get,
                        "tool": tool_name,
                        "error": error_message,
                        "elapsed": 0,
                    }
                )

        # api_keys values are intentionally not logged anywhere in this handler
        start = time.monotonic()
        try:
            result = await _RUNNERS[tool_name](req.input, req.timeout, req.api_keys or {})
            elapsed = round(time.monotonic() - start, 2)
            return {"status": "ok", "output": result, "tool": tool_name, "elapsed": elapsed}
        except Exception as exc:
            elapsed = round(time.monotonic() - start, 2)
            return JSONResponse(
                {"status": "error", "output": str(exc), "tool": tool_name, "elapsed": elapsed},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/stream/{tool_name}  — Server-Sent Events
    # ------------------------------------------------------------------

    @app.get("/api/stream/{tool_name}")
    async def stream_tool(request: Request, tool_name: str, input: str, timeout: int = 120):
        if tool_name not in _RUNNERS:

            async def _err() -> AsyncIterator[dict]:
                yield {"data": json.dumps({"line": f"Unknown tool: {tool_name}", "done": False})}
                yield {"data": json.dumps({"line": "", "done": True, "elapsed": 0})}

            return EventSourceResponse(_err(), ping=15)

        # This endpoint has no BYOK parameter — it always falls back to a
        # locally-held env-var key. When restricted that must never happen,
        # so every credentialed tool (and breach unconditionally) is blocked
        # here outright rather than gated. Use POST /api/tools/{tool}/run with
        # a caller-supplied key instead.
        restricted, restriction_reason = _request_restriction(request)
        _meta = next((m for m in _TOOL_CATALOG if m["name"] == tool_name), None)
        _needs_operator_key = bool(
            (_meta and _meta.get("requires_env")) or tool_name in _OPTIONAL_OPERATOR_KEY_ENV
        )
        if restricted and (tool_name == "search_breach" or _needs_operator_key):

            async def _blocked() -> AsyncIterator[dict]:
                msg = (
                    f"Breach-data lookups are disabled: {restriction_reason}."
                    if tool_name == "search_breach"
                    else (
                        f"This tool requires an API key ({restriction_reason}, so a "
                        "locally-held key cannot be used). Use POST /api/tools/{tool}/run "
                        "with your own key, or self-host with your own .env."
                    )
                )
                yield {"data": json.dumps({"line": msg, "done": False})}
                yield {"data": json.dumps({"line": "", "done": True, "elapsed": 0})}

            return EventSourceResponse(_blocked(), ping=15)

        async def event_gen() -> AsyncIterator[dict]:
            yield {
                "data": json.dumps({"line": f"[*] Running {tool_name} on: {input}", "done": False})
            }
            yield {"data": json.dumps({"line": "", "done": False})}
            start = time.monotonic()
            try:
                result = await _RUNNERS[tool_name](input, timeout)
                elapsed = round(time.monotonic() - start, 2)
                for line in result.splitlines():
                    if await request.is_disconnected():
                        return
                    yield {"data": json.dumps({"line": line, "done": False})}
                    await asyncio.sleep(0.012)
                yield {"data": json.dumps({"line": "", "done": True, "elapsed": elapsed})}
            except Exception as exc:
                elapsed = round(time.monotonic() - start, 2)
                yield {"data": json.dumps({"line": f"Error: {exc}", "done": False})}
                yield {"data": json.dumps({"line": "", "done": True, "elapsed": elapsed})}

        return EventSourceResponse(event_gen(), ping=15)

    # ------------------------------------------------------------------
    # GET /api/chat/test — lightweight backend connectivity check
    # ------------------------------------------------------------------

    @app.get("/api/chat/test")
    async def chat_test():
        has_claude = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
        if has_claude:
            return {"status": "ok", "backend": "claude", "ollama_reachable": None}

        # OpenAI-compatible endpoint (LiteLLM, llama-swap, vLLM, …).
        openai_base = os.environ.get("OPENAI_BASE_URL", "").strip().rstrip("/")
        if openai_base:
            api_key = os.environ.get("OPENAI_API_KEY", "").strip()
            probe = await _probe_openai_endpoint(openai_base, api_key)
            # Reachable means the backend is configured & answering, even if the
            # key is rejected (401/403) — the chat path will surface the auth
            # error clearly rather than being silently blocked as "none".
            return {
                "status": "ok",
                "backend": "openai" if probe["reachable"] else "none",
                "openai_reachable": probe["reachable"],
                "openai_auth_ok": probe["auth_ok"],
                "openai_status_code": probe["status_code"],
                "openai_base_url": openai_base,
            }

        ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        try:
            if _httpx is not None:
                async with _httpx.AsyncClient(timeout=1.5, follow_redirects=False) as client:
                    r = await client.get(f"{ollama_host}/api/tags")
                    reachable = r.status_code == 200
            else:
                raw = await asyncio.to_thread(
                    lambda: _requests.get(f"{ollama_host}/api/tags", timeout=1.5)
                )
                reachable = raw.status_code == 200
        except Exception:
            reachable = False

        return {
            "status": "ok",
            "backend": "ollama" if reachable else "none",
            "ollama_reachable": reachable,
        }

    # ------------------------------------------------------------------
    # POST /api/openai/test — probe an OpenAI-compatible endpoint from the
    # server (the browser cannot: an http:// endpoint is blocked as
    # mixed-content from the https:// UI, and cross-origin requests fail CORS).
    # Accepts the values typed in Settings so the user can test before saving.
    # ------------------------------------------------------------------

    @app.post("/api/openai/test")
    async def openai_test(req: OpenAITestRequest, request: Request):
        # Same coupling bug as /api/chat (GHSA-q6cw-g86h-m2cq), and arguably
        # worse here: this endpoint echoes the probe result back to the
        # caller, making it a non-blind SSRF oracle for internal port
        # scanning if the destination/credential split isn't enforced.
        if _byo_backend_enabled():
            _check_browser_origin(request)

        if req.openai_base_url:
            if not _byo_backend_enabled():
                _reject_client_backend()
            base_url = await _validate_outbound_base_url(req.openai_base_url)
            api_key = (req.openai_api_key or "").strip()  # no os.environ fallback, ever
        else:
            base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
            api_key = os.environ.get("OPENAI_API_KEY", "").strip()

        if not base_url:
            return {"status": "ok", "reachable": False, "auth_ok": False, "status_code": None}
        probe = await _probe_openai_endpoint(base_url, api_key)
        return {"status": "ok", **probe, "openai_base_url": base_url.rstrip("/")}

    # ------------------------------------------------------------------
    # POST /api/chat  — AI chat with tool_use, SSE streaming
    # ------------------------------------------------------------------

    @app.post("/api/chat")
    async def chat(req: ChatRequest, request: Request):
        restricted, restriction_reason = _request_restriction(request)
        if restricted:
            async def _demo_block():
                message = f"Server-side LLM is disabled ({restriction_reason}) — add your own API key in Settings."
                yield f'data: {json.dumps({"type": "error", "message": message})}\n\n'
                yield f'data: {json.dumps({"type": "done"})}\n\n'
            return StreamingResponse(
                _demo_block(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        if _byo_backend_enabled():
            _check_browser_origin(request)

        messages: list[dict] = []
        for h in req.history:
            role = h.get("role", "user")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": req.message})

        backend = _select_chat_backend(req)

        # Resolve backend-specific connection params up front (not inside the
        # generator) so a validation failure returns a proper HTTP error
        # instead of being swallowed as an SSE event after streaming started.
        openai_base_url = ""
        openai_api_key = ""
        openai_model = ""
        ollama_host = ""

        if backend == "openai":
            if req.openai_base_url:
                if not _byo_backend_enabled():
                    _reject_client_backend()
                openai_base_url = await _validate_outbound_base_url(req.openai_base_url)
                openai_api_key = (req.openai_api_key or "").strip()  # no os.environ fallback, ever
            else:
                openai_base_url = os.environ.get("OPENAI_BASE_URL", "http://localhost:8080/v1")
                openai_api_key = os.environ.get("OPENAI_API_KEY", "")
            openai_model = (req.openai_model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")).strip()
        elif backend == "ollama":
            default_ollama = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
            if req.ollama_host and req.ollama_host.rstrip("/") != default_ollama.rstrip("/"):
                if not _byo_backend_enabled():
                    _reject_client_backend()
                ollama_host = await _validate_outbound_base_url(req.ollama_host)
            else:
                ollama_host = default_ollama

        async def generate():
            if backend == "openai":
                gen = _stream_openai(messages, openai_base_url, openai_api_key, openai_model)
            elif backend == "ollama":
                gen = _stream_ollama(messages, ollama_host, req.ollama_model)
            else:
                gen = _stream_claude(messages)

            async for event in gen:
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ------------------------------------------------------------------
    # POST /api/setup  — save API keys to .env
    # ------------------------------------------------------------------

    @app.post("/api/setup")
    async def setup(request: Request):
        # GHSA-cqr4-hcfp-m6m4: this endpoint writes to live process env vars
        # and .env, so it must never be reachable from the network. Loopback
        # callers are always allowed; anyone else needs OPENOSINT_SETUP_TOKEN.
        if not _setup_request_is_authorized(request):
            return JSONResponse(
                {
                    "status": "error",
                    "message": "Setup is only allowed from localhost, or with a valid X-Setup-Token.",
                },
                status_code=403,
            )

        body: dict = await request.json()
        env_path = _ROOT / ".env"
        existing: dict[str, str] = {}
        if env_path.exists():
            for raw in env_path.read_text().splitlines():
                line = raw.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    existing[k.strip()] = v.strip()

        applied: list[str] = []
        rejected: list[str] = []
        for k, v in body.items():
            key = str(k).strip()
            v_str = str(v).strip()
            if not v_str:
                continue
            if key not in _SETUP_ALLOWED_KEYS:
                rejected.append(key)
                continue
            if key in _SETUP_URL_KEYS and not _is_valid_base_url(v_str):
                rejected.append(key)
                continue
            existing[key] = v_str
            os.environ[key] = v_str
            applied.append(key)

        env_path.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n")
        return {"status": "ok", "applied": applied, "rejected": rejected}

    # ------------------------------------------------------------------
    # POST /api/demo/chat  — pre-scripted demo stream, no API key needed
    # ------------------------------------------------------------------

    # TODO: /api/demo/chat is currently unwired from the UI — decide wire-or-delete post-deploy
    @app.post("/api/demo/chat")
    async def demo_chat(req: ChatRequest):
        async def generate():
            async for event in _demo_chat_stream(req.message):
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ------------------------------------------------------------------
    # Graph routes — read the LOCAL SQLite graph store only. No outbound
    # network calls of any kind. followthemoney is imported lazily inside
    # each handler (via openosint.graph.web_view / .review) so a missing
    # `graph` extra degrades to 503 here and leaves every other route working.
    # ------------------------------------------------------------------

    @app.get("/api/graph/subgraph")
    async def graph_subgraph(
        entity_id: str,
        depth: int = 1,
        cross_layer: bool = False,
        dataset: str | None = None,
    ):
        try:
            from openosint.graph.web_view import (
                build_subgraph,
                is_valid_entity_id,
                open_default_store,
            )
        except ImportError:
            return _graph_unavailable()

        if not is_valid_entity_id(entity_id):
            raise HTTPException(400, "invalid entity_id")
        if depth < 0:
            raise HTTPException(400, "depth must be >= 0")
        if dataset is not None and not dataset.strip():
            dataset = None

        def _work() -> dict:
            store = open_default_store()
            try:
                return build_subgraph(
                    store,
                    entity_id=entity_id,
                    depth=depth,
                    cross_layer=cross_layer,
                    dataset=dataset,
                )
            finally:
                store.close()

        return await asyncio.to_thread(_work)

    @app.get("/api/graph/entity")
    async def graph_entity(entity_id: str):
        try:
            from openosint.graph.web_view import (
                entity_detail,
                is_valid_entity_id,
                open_default_store,
            )
        except ImportError:
            return _graph_unavailable()

        if not is_valid_entity_id(entity_id):
            raise HTTPException(400, "invalid entity_id")

        def _work() -> dict | None:
            store = open_default_store()
            try:
                return entity_detail(store, entity_id)
            finally:
                store.close()

        detail = await asyncio.to_thread(_work)
        if detail is None:
            raise HTTPException(404, "entity not found")
        return detail

    @app.get("/api/graph/review/candidates")
    async def graph_review_candidates(
        schema: str | None = None,
        min_score: float | None = None,
        max_score: float | None = None,
        dataset: str | None = None,
    ):
        try:
            from dataclasses import asdict

            from openosint.graph.review import list_review_candidates
            from openosint.graph.web_view import open_default_store
        except ImportError:
            return _graph_unavailable()

        def _work() -> list[dict]:
            store = open_default_store()
            try:
                candidates = list_review_candidates(
                    store,
                    schema=schema,
                    min_score=min_score,
                    max_score=max_score,
                    dataset=dataset,
                )
                return [asdict(c) for c in candidates]
            finally:
                store.close()

        return {"candidates": await asyncio.to_thread(_work)}

    @app.post("/api/graph/review/decide")
    async def graph_review_decide(req: GraphDecideRequest):
        try:
            from openosint.graph.review import decide_review_candidate
            from openosint.graph.web_view import (
                is_valid_entity_id,
                latest_resolution_for_pair,
                open_default_store,
            )
        except ImportError:
            return _graph_unavailable()

        if req.decision not in ("accept", "reject"):
            raise HTTPException(400, "decision must be 'accept' or 'reject'")
        if not is_valid_entity_id(req.entity_id) or not is_valid_entity_id(req.canonical_id):
            raise HTTPException(400, "invalid entity_id or canonical_id")
        if req.entity_id == req.canonical_id:
            raise HTTPException(400, "entity_id and canonical_id must differ")

        judgement = "positive" if req.decision == "accept" else "negative"

        def _work() -> dict:
            from datetime import datetime, timezone

            store = open_default_store()
            try:
                # Idempotent: if the pair's latest row already carries this
                # judgement, a repeat click (or replay) appends nothing —
                # return the existing resolution, keeping decision history clean.
                existing = latest_resolution_for_pair(store, req.entity_id, req.canonical_id)
                if existing is not None and existing.judgement == judgement:
                    resolution_id = existing.id
                    idempotent = True
                else:
                    resolution = decide_review_candidate(
                        store,
                        entity_id=req.entity_id,
                        canonical_id=req.canonical_id,
                        judgement=judgement,
                        decided_at=datetime.now(timezone.utc),
                        reviewer_id=req.reviewer_id,
                    )
                    resolution_id = resolution.id
                    idempotent = False

                canonical = store.canonical_for(req.entity_id)
                return {
                    "status": "ok",
                    "resolution_id": resolution_id,
                    "idempotent": idempotent,
                    "judgement": judgement,
                    "decision": req.decision,
                    "entity_id": req.entity_id,
                    "canonical_id": req.canonical_id,
                    "canonical": canonical,
                    "cluster": store.members_of_canonical(canonical),
                }
            finally:
                store.close()

        return await asyncio.to_thread(_work)

    @app.get("/graph", include_in_schema=False)
    async def graph_page():
        page = _WEB_DIR / "graph.html"
        if page.exists():
            return HTMLResponse(page.read_text())
        return HTMLResponse("<h1>graph.html not found</h1>", status_code=404)

    # ------------------------------------------------------------------
    # Static mounts — docs, then catch-all for frontend
    # ------------------------------------------------------------------

    docs_path = _ROOT / "docs"
    if docs_path.exists():
        app.mount("/docs", StaticFiles(directory=str(docs_path), html=True), name="docs")

    web_static = _WEB_DIR / "static"
    if web_static.exists():
        app.mount("/static", StaticFiles(directory=str(web_static)), name="static")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        index = _WEB_DIR / "index.html"
        if index.exists():
            return HTMLResponse(index.read_text())
        return HTMLResponse(
            "<h1>OpenOSINT</h1>"
            "<p><strong>web/index.html not found.</strong></p>"
            "<p>If you installed via pip, this is a packaging issue — please report it at "
            "https://github.com/OpenOSINT/OpenOSINT/issues</p>"
            "<p>If running from source, make sure <code>openosint/web/index.html</code> exists.</p>",
            status_code=404,
        )

    return app


# ---------------------------------------------------------------------------
# Entry points (called from cli.py)
# ---------------------------------------------------------------------------


def _require_safe_bind(host: str, allow_remote: bool) -> None:
    """Refuse to bind to a non-loopback interface without an explicit opt-in.

    GHSA-cqr4-hcfp-m6m4: binding 0.0.0.0 by default put /api/setup (and every
    other route) on the network unintentionally.
    """
    if host in _SAFE_BIND_HOSTS:
        return
    if allow_remote or os.environ.get("OPENOSINT_ALLOW_REMOTE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return
    raise SystemExit(
        f"Refusing to bind to {host!r}: this exposes the server to the network. "
        "Pass --allow-remote (or set OPENOSINT_ALLOW_REMOTE=1) if that's intended, "
        "and put it behind a firewall/reverse proxy."
    )


async def serve_async(host: str = "127.0.0.1", port: int = 8080, allow_remote: bool = False) -> None:
    """Run uvicorn within an already-running asyncio event loop."""
    _require_safe_bind(host, allow_remote)
    load_dotenv()
    app = create_app(host=host)
    _print_banner(host, port)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", loop="none")
    server = uvicorn.Server(config)
    await server.serve()


def run_server(host: str = "127.0.0.1", port: int = 8080, allow_remote: bool = False) -> None:
    """Standalone blocking entry point."""
    _require_safe_bind(host, allow_remote)
    load_dotenv()
    app = create_app(host=host)
    _print_banner(host, port)
    uvicorn.run(app, host=host, port=port, log_level="warning")


def _print_banner(host: str, port: int) -> None:
    display = "localhost" if host in ("0.0.0.0", "") else host
    print(f"[*] OpenOSINT {_VERSION} web server")
    print(f"[*] App  → http://{display}:{port}/")
    print(f"[*] Docs → http://{display}:{port}/docs/")
    if _is_loopback_host(host) and not OPENOSINT_TRUSTED_PROXY:
        print(
            "[*] Bound to loopback. If you put a reverse proxy in front of this, "
            "set OPENOSINT_TRUSTED_PROXY=true — otherwise credentialed tools and "
            "chat will refuse proxied requests. See the README before doing so."
        )
    print("[*] Press Ctrl+C to stop.")
