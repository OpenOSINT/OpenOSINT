"""
Tests for OpenOSINT Cloud MCP gateway (/mcp endpoint).

Strategy: test the business-logic layer directly (no MCP protocol wire format
needed) by manipulating _customer_ctx and mocking tools.dispatch.

Coverage:
  (a) valid key decrements credits on success
  (b) invalid / missing key returns a clean error string, credits untouched
  (c) only the 5 allowed infrastructure tools are registered; unlisted tools absent
  (d) empty target returns a structured error without touching the network or credits
  (e) zero credits returns a clean out-of-credits message, no dispatch
  (f) missing BYOK key returns a structured error, credits untouched
  (g) upstream tool error does not decrement credits
  (h) auth middleware extracts Bearer token and sets _customer_ctx correctly
"""
from __future__ import annotations

import contextlib
import json
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from cloud import db, keys
from cloud.main import _lifespan, app
from cloud.routes.mcp_gateway import (
    _AuthMiddleware,
    _customer_ctx,
    _mcp,
    _run_mcp_tool,
)
from cloud.tools import ALLOW_LIST as _REST_ALLOW_LIST

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_memory_store():
    db._MEMORY_CUSTOMERS.clear()
    keys._MEMORY_KEYS.clear()
    keys._fernet = None
    yield


def _seed(api_key: str, credits: int = 10, plan: str = "starter") -> db.Customer:
    customer = db.Customer(
        api_key=api_key,
        credits=credits,
        plan=plan,
    )
    db._MEMORY_CUSTOMERS[api_key] = customer
    return customer


@contextlib.asynccontextmanager
async def _as_customer(customer: db.Customer | None):
    """Inject customer into _customer_ctx for the duration of a test block."""
    token = _customer_ctx.set(customer)
    try:
        yield
    finally:
        _customer_ctx.reset(token)


# ── (a) valid key decrements credits ─────────────────────────────────────────


async def test_valid_key_decrements_credits_on_success():
    customer = _seed("key-mcp-ok", credits=5)
    fake_result = {
        "tool": "search_dns",
        "target": "example.com",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "results": ["[+] A: 93.184.216.34"],
        "error": None,
    }
    async with _as_customer(customer):
        with patch("cloud.tools.dispatch", new=AsyncMock(return_value=fake_result)):
            result = await _run_mcp_tool("search_dns", "example.com")

    assert "[+] A: 93.184.216.34" in result
    assert db._MEMORY_CUSTOMERS["key-mcp-ok"].credits == 4


# ── (b) invalid / missing key ─────────────────────────────────────────────────


async def test_missing_key_returns_clean_error():
    async with _as_customer(None):
        result = await _run_mcp_tool("search_dns", "example.com")

    assert "Error:" in result
    assert "API key" in result


async def test_missing_key_does_not_touch_credits():
    _seed("key-mcp-noauth", credits=5)
    async with _as_customer(None):
        await _run_mcp_tool("search_dns", "example.com")

    assert db._MEMORY_CUSTOMERS["key-mcp-noauth"].credits == 5


# ── (c) only 5 allowed tools registered ──────────────────────────────────────

_EXPECTED_MCP_TOOLS = {
    "search_ip",
    "search_ip2location",
    "search_abuseipdb",
    "search_dns",
    "search_domain",
    "search_virustotal",
    "search_censys",
}


def test_mcp_tool_set_matches_rest_allow_list():
    registered = {t.name for t in _mcp._tool_manager.list_tools()}
    assert registered == _EXPECTED_MCP_TOOLS


def test_mcp_tool_set_matches_rest_allow_list_keys():
    registered = {t.name for t in _mcp._tool_manager.list_tools()}
    assert registered == set(_REST_ALLOW_LIST.keys())


def test_unlisted_tools_not_in_mcp():
    registered = {t.name for t in _mcp._tool_manager.list_tools()}
    for blocked in ("search_email", "search_username", "search_breach", "search_paste"):
        assert blocked not in registered


# ── (d) empty target returns structured error ─────────────────────────────────


async def test_empty_target_returns_structured_error():
    customer = _seed("key-mcp-empty", credits=5)
    async with _as_customer(customer):
        result = await _run_mcp_tool("search_ip", "")

    assert "Error:" in result
    assert "target" in result.lower()


async def test_whitespace_target_returns_structured_error():
    customer = _seed("key-mcp-ws", credits=5)
    async with _as_customer(customer):
        result = await _run_mcp_tool("search_ip", "   ")

    assert "Error:" in result


async def test_empty_target_does_not_decrement_credits():
    customer = _seed("key-mcp-empty2", credits=5)
    async with _as_customer(customer):
        await _run_mcp_tool("search_ip", "")

    assert db._MEMORY_CUSTOMERS["key-mcp-empty2"].credits == 5


# ── (e) zero credits returns clean message, no dispatch ──────────────────────


async def test_zero_credits_returns_out_of_credits_message():
    customer = _seed("key-mcp-zero", credits=0)
    async with _as_customer(customer):
        result = await _run_mcp_tool("search_dns", "example.com")

    assert "No credits remaining" in result


async def test_zero_credits_does_not_call_dispatch():
    customer = _seed("key-mcp-zero2", credits=0)
    async with _as_customer(customer):
        with patch("cloud.tools.dispatch", new=AsyncMock()) as mock_dispatch:
            await _run_mcp_tool("search_dns", "example.com")

    mock_dispatch.assert_not_called()


# ── (f) missing BYOK key returns error, credits untouched ────────────────────


async def test_missing_byok_key_returns_structured_error():
    customer = _seed("key-mcp-byok", credits=5)
    async with _as_customer(customer):
        result = await _run_mcp_tool("search_ip", "1.2.3.4")

    assert "Error:" in result
    assert "ipinfo" in result


async def test_missing_byok_key_does_not_decrement_credits():
    customer = _seed("key-mcp-byok2", credits=5)
    async with _as_customer(customer):
        await _run_mcp_tool("search_ip", "1.2.3.4")

    assert db._MEMORY_CUSTOMERS["key-mcp-byok2"].credits == 5


# ── (g) upstream tool error does not decrement credits ───────────────────────


async def test_upstream_error_does_not_decrement_credits():
    customer = _seed("key-mcp-err", credits=5)
    error_result = {
        "tool": "search_dns",
        "target": "example.com",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "results": ["Scan error: DNS lookup failed"],
        "error": None,
    }
    async with _as_customer(customer):
        with patch("cloud.tools.dispatch", new=AsyncMock(return_value=error_result)):
            result = await _run_mcp_tool("search_dns", "example.com")

    assert "Scan error" in result
    assert db._MEMORY_CUSTOMERS["key-mcp-err"].credits == 5


# ── (h) auth middleware extracts Bearer token ─────────────────────────────────


async def test_auth_middleware_sets_customer_from_bearer_token():
    _seed("mcp-bearer-key", credits=3)
    captured: list[db.Customer | None] = []

    async def _probe(scope, receive, send):
        captured.append(_customer_ctx.get())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def _noop_receive():
        return {}

    async def _noop_send(msg):
        pass

    middleware = _AuthMiddleware(_probe)
    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer mcp-bearer-key")],
    }

    await middleware(scope, _noop_receive, _noop_send)

    assert len(captured) == 1
    assert captured[0] is not None
    assert captured[0].api_key == "mcp-bearer-key"


async def test_auth_middleware_sets_none_for_invalid_key():
    captured: list[db.Customer | None] = []

    async def _probe(scope, receive, send):
        captured.append(_customer_ctx.get())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def _noop_receive():
        return {}

    async def _noop_send(msg):
        pass

    middleware = _AuthMiddleware(_probe)
    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer not-a-real-key")],
    }

    await middleware(scope, _noop_receive, _noop_send)
    assert captured[0] is None


async def test_auth_middleware_sets_none_for_missing_header():
    captured: list[db.Customer | None] = []

    async def _probe(scope, receive, send):
        captured.append(_customer_ctx.get())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def _noop_receive():
        return {}

    async def _noop_send(msg):
        pass

    middleware = _AuthMiddleware(_probe)
    scope = {"type": "http", "headers": []}

    await middleware(scope, _noop_receive, _noop_send)
    assert captured[0] is None


async def test_mounted_mcp_app_completes_initialize_and_tools_list():
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0"},
        },
    }

    async with _lifespan(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
        ) as client:
            response = await client.post(
                "/mcp/",
                headers={
                    "accept": "application/json, text/event-stream",
                    "content-type": "application/json",
                },
                json=initialize,
            )

            assert response.status_code == 200
            session_id = response.headers.get("mcp-session-id")
            assert session_id

            response = await client.post(
                "/mcp/",
                headers={
                    "accept": "application/json, text/event-stream",
                    "content-type": "application/json",
                    "mcp-session-id": session_id,
                },
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            )

    assert response.status_code == 200
    payload = json.loads(
        next(
            line.removeprefix("data: ")
            for line in response.text.splitlines()
            if line.startswith("data:")
        )
    )
    assert {tool["name"] for tool in payload["result"]["tools"]} == _EXPECTED_MCP_TOOLS


# ── (i) Shodan attribution reaches the MCP text result ───────────────────────


async def test_shodan_attribution_reaches_mcp_text_result():
    """_run_mcp_tool's return value is the exact string FastMCP wraps as the
    tool's TextContent block — what an MCP client renders to the user. Real
    dispatch() runs here; only the low-level upstream call is mocked.

    search_shodan is deliberately absent from ALLOW_LIST (no SHODAN_API_KEY
    in prod yet, see cloud/tools.py) and no longer registered as an MCP tool
    — reinject it into ALLOW_LIST for this test only so _run_mcp_tool's
    dispatch() call still exercises the real attribution path."""
    from cloud.tools import _SHODAN_ENTRY

    customer = _seed("key-mcp-shodan-attr", credits=10)

    with patch.dict("cloud.tools.ALLOW_LIST", {"search_shodan": _SHODAN_ENTRY}):
        with patch("cloud.tools.run_shodan_osint", new=AsyncMock(return_value="[Shodan] Host: 1.2.3.4")):
            with patch.dict(os.environ, {"SHODAN_API_KEY": "srv_shodan_key"}):
                async with _as_customer(customer):
                    result = await _run_mcp_tool("search_shodan", "1.2.3.4")

    assert result == "[Shodan] Host: 1.2.3.4\nData provided by Shodan (shodan.io)."
