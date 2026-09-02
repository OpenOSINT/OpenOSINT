"""
OpenOSINT Cloud — hosted MCP server endpoint (Streamable HTTP transport).

Mounted at /mcp inside the existing FastAPI app (cloud/main.py).
Exposes exactly the same tools as /v1/enrich (cloud/tools.ALLOW_LIST).
No person-search, breach, or leaked-data tools.

Auth: Authorization: Bearer <openosint-cloud-api-key>
Metering: per-tool credit cost (see cloud/key_sources.get_credit_cost) — same
rules as /v1/enrich. Platform-pool tools are also burst-limited per tenant.
All existing functions (dispatch, resolve_key, decrement_credits) are reused.
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextvars import ContextVar

from mcp.server.fastmcp import FastMCP
from starlette.types import ASGIApp, Receive, Scope, Send

from cloud import db, rate_limit, tools
from cloud.config import TOOL_TIMEOUT_SECONDS
from cloud.key_sources import get_credit_cost, is_platform_pool_tool, resolve_key
from cloud.routes.enrich import _log_outcome

logger = logging.getLogger(__name__)

# ── per-request customer, set by _AuthMiddleware before the MCP handler runs ─
_customer_ctx: ContextVar[db.Customer | None] = ContextVar("_mcp_customer", default=None)

_ERROR_PREFIXES = ("Scan error", "Internal error", "Error:")

# ── FastMCP instance ──────────────────────────────────────────────────────────
# streamable_http_path="/" because FastAPI mounts this at /mcp and Starlette
# strips the /mcp prefix before passing the request to the sub-app.
_mcp = FastMCP(
    "OpenOSINT Cloud",
    streamable_http_path="/",
)


def _credits_error(plan: str) -> str:
    return "No credits remaining. Contact commercial@openosint.tech for access."


async def _run_mcp_tool(tool_name: str, target: str) -> str:
    """
    Common MCP tool handler: validate input → auth → key resolution →
    dispatch → meter. Returns a plain-text result or a structured error string.
    Never raises — MCP tool handlers must not throw to avoid protocol 500s.
    """
    if not target or not target.strip():
        return (
            f"Error: 'target' is required for {tool_name}. "
            "Provide an IP address or domain name."
        )

    customer = _customer_ctx.get()
    if customer is None:
        return (
            "Error: Invalid or missing API key. "
            "Pass your OpenOSINT Cloud key as: Authorization: Bearer <key>"
        )

    try:
        upstream_key = await resolve_key(tool_name, customer.api_key)
    except ValueError as exc:
        return f"Error: {exc}"

    if is_platform_pool_tool(tool_name) and not rate_limit.platform_pool_limiter.allow(
        f"{customer.api_key}:{tool_name}"
    ):
        return f"Error: Too many '{tool_name}' requests. Please slow down and try again shortly."

    cost = get_credit_cost(tool_name)
    if customer.credits < cost:
        return _credits_error(customer.plan)

    start = time.monotonic()
    try:
        result = await asyncio.wait_for(
            tools.dispatch(tool_name, target.strip(), api_key=upstream_key),
            timeout=float(TOOL_TIMEOUT_SECONDS),
        )
    except asyncio.TimeoutError:
        _log_outcome(tool_name, customer.api_key, "timeout", time.monotonic() - start)
        return f"Error: Tool '{tool_name}' timed out after {TOOL_TIMEOUT_SECONDS}s."
    except ValueError as exc:
        _log_outcome(tool_name, customer.api_key, "error", time.monotonic() - start)
        return f"Error: {exc}"
    elapsed = time.monotonic() - start

    lines: list[str] = result.get("results", [])
    first_line = lines[0] if lines else (result.get("error") or "")
    is_error = any(first_line.startswith(p) for p in _ERROR_PREFIXES)

    if not is_error:
        new_credits = await db.decrement_credits(customer.api_key, cost)
        if new_credits is None:
            # Race condition: concurrent request drained the last credit
            _log_outcome(tool_name, customer.api_key, "credits_exhausted", elapsed)
            return _credits_error(customer.plan)
        _log_outcome(tool_name, customer.api_key, "ok", elapsed)
    else:
        _log_outcome(tool_name, customer.api_key, "upstream_error", elapsed)

    return "\n".join(lines) if lines else (result.get("error") or "No results.")


# ── MCP tool registrations (5 infrastructure tools, same as ALLOW_LIST) ──────

@_mcp.tool(description=(
    "Retrieve geolocation, ASN, and host data for an IP address via ipinfo.io. "
    "Returns country, city, organisation, hostname, and timezone."
))
async def search_ip(target: str) -> str:
    """target: IPv4 or IPv6 address (e.g. 8.8.8.8)"""
    return await _run_mcp_tool("search_ip", target)


@_mcp.tool(description=(
    "Enhanced IP intelligence: geolocation, ISP, VPN/Proxy/Tor/datacenter detection, "
    "threat score. Sponsored by IP2Location.io — server key included, no setup required."
))
async def search_ip2location(target: str) -> str:
    """target: IPv4 or IPv6 address (e.g. 8.8.8.8)"""
    return await _run_mcp_tool("search_ip2location", target)


@_mcp.tool(description=(
    "Check an IP address against AbuseIPDB for malicious activity reports, "
    "abuse confidence score, total reports, and ISP."
))
async def search_abuseipdb(target: str) -> str:
    """target: IPv4 or IPv6 address (e.g. 8.8.8.8)"""
    return await _run_mcp_tool("search_abuseipdb", target)


@_mcp.tool(description=(
    "Enumerate DNS records for a domain: A, AAAA, MX, NS, TXT, CNAME, SOA."
))
async def search_dns(target: str) -> str:
    """target: Fully qualified domain name (e.g. example.com)"""
    return await _run_mcp_tool("search_dns", target)


@_mcp.tool(description=(
    "Enumerate subdomains for a target domain via passive DNS intelligence sources."
))
async def search_domain(target: str) -> str:
    """target: Apex domain name (e.g. example.com)"""
    return await _run_mcp_tool("search_domain", target)


# ponytail: search_shodan intentionally not registered here — see the same
# note in cloud/tools.py. Add the @_mcp.tool block back once ALLOW_LIST has it.

@_mcp.tool(description=(
    "Check an IP, domain, URL, or file hash against VirusTotal's 70+ antivirus "
    "and URL/domain reputation engines."
))
async def search_virustotal(target: str) -> str:
    """target: IPv4 address, domain, URL, or file hash (MD5/SHA-1/SHA-256)"""
    return await _run_mcp_tool("search_virustotal", target)


@_mcp.tool(description=(
    "Look up an IP host (open ports, services, ASN) or domain certificates "
    "(SANs, issuer, validity dates) via Censys."
))
async def search_censys(target: str) -> str:
    """target: IPv4 address or domain name"""
    return await _run_mcp_tool("search_censys", target)


# ── auth middleware ───────────────────────────────────────────────────────────

class _AuthMiddleware:
    """
    Raw ASGI middleware: extract Authorization: Bearer <key>, look up the
    customer, and store it in _customer_ctx before the MCP handler runs.

    Uses a raw ASGI wrapper (not BaseHTTPMiddleware) to guarantee that
    ContextVar values set here are visible inside the tool handlers.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers: dict[bytes, bytes] = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            api_key = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            customer = await db.get_customer(api_key) if api_key else None
            token = _customer_ctx.set(customer)
            try:
                await self._app(scope, receive, send)
            finally:
                _customer_ctx.reset(token)
        else:
            await self._app(scope, receive, send)


# ── ASGI app factory ──────────────────────────────────────────────────────────

def create_mcp_asgi_app() -> ASGIApp:
    """Return the FastMCP Starlette app wrapped with the auth middleware."""
    starlette_app = _mcp.streamable_http_app()
    return _AuthMiddleware(starlette_app)
