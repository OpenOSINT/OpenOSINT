# tests/test_web_server.py
"""
Unit tests for web_server.py Ollama streaming, tool-argument handling,
BYOK key threading, CORS, rate limiting, and /api/tools metadata.

All HTTP calls are mocked — no live server or API keys required.
"""

from __future__ import annotations

import json
import logging
import os
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_requests_response(status_code: int = 200, body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    body = body or {}
    resp.text = json.dumps(body)[:200]
    resp.json.return_value = body
    return resp


async def _collect(gen) -> list[dict]:
    items: list[dict] = []
    async for item in gen:
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# _stream_ollama — happy path
# ---------------------------------------------------------------------------


class TestStreamOllamaNormalResponse:
    async def test_plain_reply_yields_text_then_done(self):
        from openosint.web_server import _stream_ollama

        body = {"message": {"role": "assistant", "content": "Hello from Ollama!"}, "done": True}
        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.return_value = _mock_requests_response(body=body)
                events = await _collect(
                    _stream_ollama(
                        [{"role": "user", "content": "hi"}],
                        "http://localhost:11434",
                        "llama3.2",
                    )
                )

        types = [e["type"] for e in events]
        assert types == ["text", "done"]
        assert events[0]["content"] == "Hello from Ollama!"

    async def test_text_content_propagated(self):
        from openosint.web_server import _stream_ollama

        body = {
            "message": {"role": "assistant", "content": "8.8.8.8 belongs to Google."},
            "done": True,
        }
        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.return_value = _mock_requests_response(body=body)
                events = await _collect(
                    _stream_ollama(
                        [{"role": "user", "content": "investigate 8.8.8.8"}],
                        "http://localhost:11434",
                        "llama3.2",
                    )
                )

        text_events = [e for e in events if e["type"] == "text"]
        assert len(text_events) == 1
        assert "Google" in text_events[0]["content"]


# ---------------------------------------------------------------------------
# _stream_ollama — null / empty content (regression: issue #7)
# ---------------------------------------------------------------------------


class TestStreamOllamaNullContent:
    async def test_null_content_no_crash_yields_done(self):
        """content=null with no tool_calls must yield done without crashing."""
        from openosint.web_server import _stream_ollama

        body = {"message": {"role": "assistant", "content": None}, "done": True}
        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.return_value = _mock_requests_response(body=body)
                events = await _collect(
                    _stream_ollama(
                        [{"role": "user", "content": "hi"}],
                        "http://localhost:11434",
                        "llama3.2",
                    )
                )

        types = [e["type"] for e in events]
        assert "done" in types
        assert "error" not in types

    async def test_empty_string_content_yields_done_only(self):
        """content='' with no tool_calls yields done without a text event."""
        from openosint.web_server import _stream_ollama

        body = {"message": {"role": "assistant", "content": ""}, "done": True}
        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.return_value = _mock_requests_response(body=body)
                events = await _collect(
                    _stream_ollama(
                        [{"role": "user", "content": "hi"}],
                        "http://localhost:11434",
                        "llama3.2",
                    )
                )

        types = [e["type"] for e in events]
        assert types == ["done"]
        assert "text" not in types

    async def test_null_tool_calls_not_iterated(self):
        """tool_calls=null is treated same as [] — no tool loop entered."""
        from openosint.web_server import _stream_ollama

        body = {
            "message": {"role": "assistant", "content": "hi", "tool_calls": None},
            "done": True,
        }
        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.return_value = _mock_requests_response(body=body)
                events = await _collect(
                    _stream_ollama(
                        [{"role": "user", "content": "hi"}],
                        "http://localhost:11434",
                        "llama3.2",
                    )
                )

        types = [e["type"] for e in events]
        assert types == ["text", "done"]
        assert "tool_start" not in types


# ---------------------------------------------------------------------------
# _stream_ollama — error paths
# ---------------------------------------------------------------------------


class TestStreamOllamaErrors:
    async def test_http_404_yields_single_error_event(self):
        from openosint.web_server import _stream_ollama

        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.return_value = _mock_requests_response(
                    status_code=404, body={"error": "model not found"}
                )
                events = await _collect(
                    _stream_ollama(
                        [{"role": "user", "content": "hi"}],
                        "http://localhost:11434",
                        "nonexistent",
                    )
                )

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "404" in events[0]["message"]

    async def test_http_500_yields_single_error_event(self):
        from openosint.web_server import _stream_ollama

        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.return_value = _mock_requests_response(status_code=500)
                events = await _collect(
                    _stream_ollama(
                        [{"role": "user", "content": "hi"}],
                        "http://localhost:11434",
                        "llama3.2",
                    )
                )

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "500" in events[0]["message"]

    async def test_connection_error_yields_error_event(self):
        from openosint.web_server import _stream_ollama

        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.side_effect = ConnectionError("connection refused")
                events = await _collect(
                    _stream_ollama(
                        [{"role": "user", "content": "hi"}],
                        "http://localhost:11434",
                        "llama3.2",
                    )
                )

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "connection refused" in events[0]["message"].lower()

    async def test_error_path_emits_no_done(self):
        """Error path must NOT emit a done event — frontend handles it via break."""
        from openosint.web_server import _stream_ollama

        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.return_value = _mock_requests_response(status_code=400)
                events = await _collect(
                    _stream_ollama(
                        [{"role": "user", "content": "hi"}],
                        "http://localhost:11434",
                        "llama3.2",
                    )
                )

        types = [e["type"] for e in events]
        assert "done" not in types


# ---------------------------------------------------------------------------
# _stream_ollama — tool call path
# ---------------------------------------------------------------------------


class TestStreamOllamaToolCalls:
    def _two_call_side_effect(self, first: dict, second: dict):
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _mock_requests_response(body=first if call_count == 1 else second)

        return side_effect

    async def test_tool_call_yields_tool_events_then_text_then_done(self):
        from openosint.web_server import _stream_ollama

        first = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "generate_dorks", "arguments": {"input": "example.com"}}}
                ],
            },
            "done": True,
        }
        second = {
            "message": {"role": "assistant", "content": "Investigation complete."},
            "done": True,
        }

        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.side_effect = self._two_call_side_effect(first, second)
                events = await _collect(
                    _stream_ollama(
                        [{"role": "user", "content": "dorks for example.com"}],
                        "http://localhost:11434",
                        "llama3.2",
                    )
                )

        types = [e["type"] for e in events]
        assert "tool_start" in types
        assert "tool_result" in types
        assert "text" in types
        assert types[-1] == "done"

    async def test_tool_start_carries_correct_tool_name_and_input(self):
        from openosint.web_server import _stream_ollama

        first = {
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"function": {"name": "generate_dorks", "arguments": {"input": "example.com"}}}
                ],
            },
            "done": True,
        }
        second = {"message": {"role": "assistant", "content": "Done."}, "done": True}

        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.side_effect = self._two_call_side_effect(first, second)
                events = await _collect(
                    _stream_ollama(
                        [{"role": "user", "content": "check example.com"}],
                        "http://localhost:11434",
                        "llama3.2",
                    )
                )

        start = next(e for e in events if e["type"] == "tool_start")
        assert start["tool"] == "generate_dorks"
        assert start["input"] == "example.com"

    async def test_non_input_key_argument_extracted_via_fallback(self):
        """When model uses 'query' instead of 'input', the fallback extracts it."""
        from openosint.web_server import _stream_ollama

        first = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "generate_dorks",
                            "arguments": {"query": "example.com"},
                        }
                    }
                ],
            },
            "done": True,
        }
        second = {"message": {"role": "assistant", "content": "Done."}, "done": True}

        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.side_effect = self._two_call_side_effect(first, second)
                events = await _collect(
                    _stream_ollama(
                        [{"role": "user", "content": "check example.com"}],
                        "http://localhost:11434",
                        "llama3.2",
                    )
                )

        start = next(e for e in events if e["type"] == "tool_start")
        assert start["input"] == "example.com"


# ---------------------------------------------------------------------------
# _run_tool — input validation (regression: holehe no-email bug, issue #7)
# ---------------------------------------------------------------------------


class TestRunToolInputValidation:
    async def test_empty_string_returns_error_not_exception(self):
        from openosint.web_server import _run_tool

        result = await _run_tool("search_email", "")
        assert isinstance(result, str)
        assert "error" in result.lower() or "required" in result.lower()

    async def test_whitespace_only_input_returns_error(self):
        from openosint.web_server import _run_tool

        result = await _run_tool("search_email", "   \t\n")
        assert isinstance(result, str)
        assert "error" in result.lower() or "required" in result.lower()

    async def test_error_message_names_the_tool(self):
        from openosint.web_server import _run_tool

        result = await _run_tool("search_email", "")
        assert "search_email" in result

    async def test_error_message_hints_at_retry(self):
        from openosint.web_server import _run_tool

        result = await _run_tool("search_whois", "")
        assert "retry" in result.lower() or "input" in result.lower()

    async def test_unknown_tool_returns_error(self):
        from openosint.web_server import _run_tool

        result = await _run_tool("nonexistent_tool", "anything")
        assert "unknown" in result.lower() or "nonexistent_tool" in result

    async def test_valid_input_delegates_to_runner(self):
        from openosint.web_server import _run_tool

        async def fake_runner(v, t):
            return f"ran:{v}"

        with patch("openosint.web_server._RUNNERS", {"test_tool": lambda v, t: fake_runner(v, t)}):
            result = await _run_tool("test_tool", "my_target")

        assert result == "ran:my_target"


# ---------------------------------------------------------------------------
# Footprint tool registration in web server
# ---------------------------------------------------------------------------


class TestSearchFootprintWebRegistration:
    def test_search_footprint_in_tool_catalog(self):
        from openosint.web_server import _TOOL_CATALOG

        names = [t["name"] for t in _TOOL_CATALOG]
        assert "search_footprint" in names

    def test_search_footprint_catalog_entry_shape(self):
        from openosint.web_server import _TOOL_CATALOG

        entry = next(t for t in _TOOL_CATALOG if t["name"] == "search_footprint")
        assert entry["category"] == "Recon"
        assert entry["icon"] == "👣"
        assert "BRIGHTDATA_API_KEY" in entry["requires_env"]
        assert "BRIGHTDATA_SERP_ZONE" in entry["requires_env"]
        assert entry["requires_binary"] == []
        assert "input_label" in entry
        assert "input_placeholder" in entry

    def test_search_footprint_in_runners(self):
        from openosint.web_server import _RUNNERS

        assert "search_footprint" in _RUNNERS

    def test_search_footprint_runner_is_callable(self):
        from openosint.web_server import _RUNNERS

        assert callable(_RUNNERS["search_footprint"])

    def test_search_footprint_in_claude_tools(self):
        from openosint.web_server import _CLAUDE_TOOLS

        names = [t["name"] for t in _CLAUDE_TOOLS]
        assert "search_footprint" in names

    async def test_run_tool_dispatches_footprint(self):
        from openosint.web_server import _run_tool

        async def fake_footprint(target, max_queries=3, timeout_seconds=30, *, api_keys=None):
            return f"footprint:{target}"

        with patch("openosint.web_server.run_footprint_osint", fake_footprint):
            result = await _run_tool("search_footprint", "john doe")

        assert result == "footprint:john doe"


# ---------------------------------------------------------------------------
# HTTP endpoint fixtures (BYOK / CORS / rate-limit / /api/tools tests)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def http_client():
    """Loopback client: simulates a self-hosted instance bound to 127.0.0.1,
    which is normal operation with no restriction — see
    TestDemoModeFailsClosed for the network-exposure invariant itself."""
    import openosint.web_server as ws

    ws._RATE_STORE.clear()
    ws._TILE_RATE_STORE.clear()
    app = ws.create_app(host="127.0.0.1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    ws._RATE_STORE.clear()
    ws._TILE_RATE_STORE.clear()


# ---------------------------------------------------------------------------
# BYOK: per-request api_keys forwarded to runner
# ---------------------------------------------------------------------------


class TestByokKeyForwarding:
    async def test_request_key_reaches_tool_runner(self, http_client):
        """api_keys in body is forwarded; runner receives the value."""
        received: list = []

        async def fake_shodan(query, timeout_seconds=30, *, api_key=None):
            received.append(api_key)
            return "ok"

        with patch("openosint.web_server.run_shodan_osint", new=fake_shodan):
            resp = await http_client.post(
                "/api/run/search_shodan",
                json={"input": "8.8.8.8", "api_keys": {"SHODAN_API_KEY": "byok-abc"}},
            )

        assert resp.status_code == 200
        assert received == ["byok-abc"]

    async def test_env_fallback_when_no_body_key(self, http_client):
        """Runner receives None when api_keys absent; tool falls back to env."""
        received: list = []

        async def fake_shodan(query, timeout_seconds=30, *, api_key=None):
            received.append(api_key)
            return "ok"

        with (
            patch("openosint.web_server.run_shodan_osint", new=fake_shodan),
            patch.dict(os.environ, {"SHODAN_API_KEY": "env-key"}),
        ):
            resp = await http_client.post(
                "/api/run/search_shodan",
                json={"input": "8.8.8.8"},
            )

        assert resp.status_code == 200
        assert received == [None]  # runner gets None; tool resolves from env

    async def test_multi_key_tool_receives_full_dict(self, http_client):
        """Multi-key tools (censys) receive the whole api_keys dict."""
        received: list = []

        async def fake_censys(target, timeout_seconds=30, *, api_keys=None):
            received.append(api_keys)
            return "ok"

        with patch("openosint.web_server.run_censys_osint", new=fake_censys):
            supplied = {"CENSYS_API_ID": "id-111", "CENSYS_SECRET": "sec-222"}
            resp = await http_client.post(
                "/api/run/search_censys",
                json={"input": "example.com", "api_keys": supplied},
            )

        assert resp.status_code == 200
        assert received[0] == supplied


# ---------------------------------------------------------------------------
# key_required structured response
# ---------------------------------------------------------------------------


class TestKeyRequired:
    async def test_missing_single_key_returns_key_required(self, http_client):
        """No key in body or env → key_required:true with the missing key listed."""
        backup = os.environ.pop("SHODAN_API_KEY", None)
        try:
            resp = await http_client.post(
                "/api/run/search_shodan",
                json={"input": "8.8.8.8"},
            )
        finally:
            if backup is not None:
                os.environ["SHODAN_API_KEY"] = backup

        assert resp.status_code == 200
        body = resp.json()
        assert body["key_required"] is True
        assert "SHODAN_API_KEY" in body["missing_keys"]
        assert body["status"] == "error"

    async def test_partial_multi_key_lists_only_missing(self, http_client):
        """Censys: supplying one key in body, other absent → only missing one listed."""
        backup_id = os.environ.pop("CENSYS_API_ID", None)
        backup_sec = os.environ.pop("CENSYS_SECRET", None)
        try:
            resp = await http_client.post(
                "/api/run/search_censys",
                json={"input": "example.com", "api_keys": {"CENSYS_API_ID": "my-id"}},
            )
        finally:
            if backup_id is not None:
                os.environ["CENSYS_API_ID"] = backup_id
            if backup_sec is not None:
                os.environ["CENSYS_SECRET"] = backup_sec

        assert resp.status_code == 200
        body = resp.json()
        assert body["key_required"] is True
        assert body["missing_keys"] == ["CENSYS_SECRET"]

    async def test_both_keys_in_body_no_key_required(self, http_client):
        """All required keys present in body → no key_required check triggered."""
        backup_id = os.environ.pop("CENSYS_API_ID", None)
        backup_sec = os.environ.pop("CENSYS_SECRET", None)

        async def fake_censys(target, timeout_seconds=30, *, api_keys=None):
            return "ok"

        try:
            with patch("openosint.web_server.run_censys_osint", new=fake_censys):
                resp = await http_client.post(
                    "/api/run/search_censys",
                    json={
                        "input": "example.com",
                        "api_keys": {"CENSYS_API_ID": "x", "CENSYS_SECRET": "y"},
                    },
                )
        finally:
            if backup_id is not None:
                os.environ["CENSYS_API_ID"] = backup_id
            if backup_sec is not None:
                os.environ["CENSYS_SECRET"] = backup_sec

        assert resp.status_code == 200
        assert resp.json().get("key_required") is None

    async def test_keyless_tool_never_gets_key_required(self, http_client):
        """search_whois (no required keys) must not return key_required."""
        async def fake_whois(domain, timeout_seconds=15):
            return "WHOIS data"

        with patch("openosint.web_server.run_whois_osint", new=fake_whois):
            resp = await http_client.post(
                "/api/run/search_whois",
                json={"input": "example.com"},
            )

        assert resp.status_code == 200
        assert resp.json().get("key_required") is None


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


class TestCors:
    async def test_preflight_allowed_origin_returns_header(self, http_client):
        resp = await http_client.options(
            "/api/tools",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code in (200, 204)
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"

    async def test_disallowed_origin_no_allow_header(self, http_client):
        resp = await http_client.get(
            "/api/tools",
            headers={"Origin": "https://attacker.example.com"},
        )
        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao != "https://attacker.example.com"

    async def test_allow_credentials_not_true(self, http_client):
        resp = await http_client.options(
            "/api/tools",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        cred = resp.headers.get("access-control-allow-credentials", "false")
        assert cred.lower() != "true"


# ---------------------------------------------------------------------------
# GET /api/tools — catalog shape
# ---------------------------------------------------------------------------


class TestToolsCatalog:
    async def test_all_entries_have_required_fields(self, http_client):
        resp = await http_client.get("/api/tools")
        assert resp.status_code == 200
        for tool in resp.json():
            assert "tool_type" in tool, f"{tool['name']} missing tool_type"
            assert tool["tool_type"] in ("A", "B")
            assert "required_keys" in tool
            assert isinstance(tool["required_keys"], list)
            assert "parameters" in tool
            assert tool["parameters"]["type"] == "object"
            assert "input" in tool["parameters"]["properties"]

    async def test_new_tools_present(self, http_client):
        resp = await http_client.get("/api/tools")
        names = {t["name"] for t in resp.json()}
        assert "search_abuseipdb" in names
        assert "search_dns" in names
        assert "search_github" in names

    async def test_subprocess_tools_are_type_b(self, http_client):
        resp = await http_client.get("/api/tools")
        type_b = {t["name"] for t in resp.json() if t["tool_type"] == "B"}
        for name in ("search_email", "search_username", "search_domain", "search_phone"):
            assert name in type_b

    async def test_abuseipdb_required_keys(self, http_client):
        resp = await http_client.get("/api/tools")
        entry = next(t for t in resp.json() if t["name"] == "search_abuseipdb")
        assert entry["required_keys"] == ["ABUSEIPDB_API_KEY"]

    async def test_censys_required_keys_both_present(self, http_client):
        resp = await http_client.get("/api/tools")
        entry = next(t for t in resp.json() if t["name"] == "search_censys")
        assert "CENSYS_API_ID" in entry["required_keys"]
        assert "CENSYS_SECRET" in entry["required_keys"]


# ---------------------------------------------------------------------------
# Rate limiting (keyless tools)
# ---------------------------------------------------------------------------


class TestRateLimiting:
    async def test_keyless_tool_blocked_after_limit(self, http_client):
        from openosint.web_server import _RL_MAX_REQS

        async def fake_whois(domain, timeout_seconds=15):
            return "ok"

        statuses = []
        with patch("openosint.web_server.run_whois_osint", new=fake_whois):
            for _ in range(_RL_MAX_REQS + 1):
                r = await http_client.post(
                    "/api/run/search_whois", json={"input": "example.com"}
                )
                statuses.append(r.status_code)

        assert statuses[0] == 200
        assert statuses[-1] == 429

    async def test_keyed_tool_not_rate_limited(self, http_client):
        """search_shodan is not in _KEYLESS_TOOLS; no 429 even without a key."""
        from openosint.web_server import _RL_MAX_REQS

        backup = os.environ.pop("SHODAN_API_KEY", None)
        try:
            statuses = []
            for _ in range(_RL_MAX_REQS + 5):
                r = await http_client.post(
                    "/api/run/search_shodan", json={"input": "8.8.8.8"}
                )
                statuses.append(r.status_code)
        finally:
            if backup is not None:
                os.environ["SHODAN_API_KEY"] = backup

        assert 429 not in statuses  # gets key_required (200), never rate-limit (429)


# ---------------------------------------------------------------------------
# GET /api/tiles/{z}/{x}/{y} — globe basemap tile proxy
# ---------------------------------------------------------------------------


class TestTileProxy:
    async def test_out_of_range_coords_return_404(self, http_client):
        r = await http_client.get("/api/tiles/2/99/99")  # x,y >= 2**z
        assert r.status_code == 404

    async def test_negative_zoom_returns_404(self, http_client):
        r = await http_client.get("/api/tiles/-1/0/0")
        assert r.status_code == 404

    async def test_zoom_above_max_returns_404(self, http_client):
        from openosint.web_server import _TILE_MAX_ZOOM

        r = await http_client.get(f"/api/tiles/{_TILE_MAX_ZOOM + 1}/0/0")
        assert r.status_code == 404

    async def test_zoom_at_max_is_allowed(self, http_client):
        import openosint.web_server as ws
        from openosint.web_server import _TILE_MAX_ZOOM

        ws._tile_cache.clear()
        mock_resp = _mock_requests_response(status_code=200)
        mock_resp.content = b"\xff\xd8\xff\xe0fakejpeg"
        with patch("openosint.web_server._requests") as mreq:
            mreq.get.return_value = mock_resp
            r = await http_client.get(f"/api/tiles/{_TILE_MAX_ZOOM}/0/0")
        assert r.status_code == 200

    async def test_happy_path_fetches_and_caches(self, http_client):
        import openosint.web_server as ws

        ws._tile_cache.clear()
        mock_resp = _mock_requests_response(status_code=200)
        mock_resp.content = b"\xff\xd8\xff\xe0fakejpeg"

        with patch("openosint.web_server._requests") as mreq:
            mreq.get.return_value = mock_resp
            r1 = await http_client.get("/api/tiles/3/4/5")
            r2 = await http_client.get("/api/tiles/3/4/5")

        assert r1.status_code == 200
        assert r1.content == b"\xff\xd8\xff\xe0fakejpeg"
        assert r1.headers["content-type"] == "image/jpeg"
        assert r2.content == r1.content
        mreq.get.assert_called_once()  # second request served from cache

    async def test_upstream_exception_returns_blank_tile(self, http_client):
        import openosint.web_server as ws

        ws._tile_cache.clear()
        with patch("openosint.web_server._requests") as mreq:
            mreq.get.side_effect = Exception("connection reset")
            r = await http_client.get("/api/tiles/3/1/1")

        assert r.status_code == 200
        assert r.headers["content-type"] == "image/gif"
        assert r.content == ws._BLANK_TILE

    async def test_upstream_non_200_returns_blank_tile(self, http_client):
        import openosint.web_server as ws

        ws._tile_cache.clear()
        mock_resp = _mock_requests_response(status_code=503)

        with patch("openosint.web_server._requests") as mreq:
            mreq.get.return_value = mock_resp
            r = await http_client.get("/api/tiles/3/2/2")

        assert r.status_code == 200
        assert r.content == ws._BLANK_TILE

    async def test_rate_limited_after_limit(self, http_client):
        from openosint.web_server import _TILE_RL_MAX_REQS
        import openosint.web_server as ws

        ws._tile_cache.clear()
        ws._TILE_RATE_STORE.clear()
        mock_resp = _mock_requests_response(status_code=200)
        mock_resp.content = b"jpegbytes"

        statuses = []
        with patch("openosint.web_server._requests") as mreq:
            mreq.get.return_value = mock_resp
            # Distinct z7 coordinates each time so the cache never masks the
            # limiter; z7 has 128x128 tiles, plenty of headroom.
            for i in range(_TILE_RL_MAX_REQS + 1):
                r = await http_client.get(f"/api/tiles/7/{i % 100}/{i // 100}")
                statuses.append(r.status_code)

        assert statuses[0] == 200
        assert statuses[-1] == 429

    async def test_cache_control_and_etag_present(self, http_client):
        import openosint.web_server as ws

        ws._tile_cache.clear()
        mock_resp = _mock_requests_response(status_code=200)
        mock_resp.content = b"\xff\xd8\xff\xe0fakejpeg"
        with patch("openosint.web_server._requests") as mreq:
            mreq.get.return_value = mock_resp
            r = await http_client.get("/api/tiles/3/6/6")

        assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert r.headers["etag"].startswith('"') and r.headers["etag"].endswith('"')

    async def test_if_none_match_returns_304(self, http_client):
        import openosint.web_server as ws

        ws._tile_cache.clear()
        mock_resp = _mock_requests_response(status_code=200)
        mock_resp.content = b"\xff\xd8\xff\xe0fakejpeg"
        with patch("openosint.web_server._requests") as mreq:
            mreq.get.return_value = mock_resp
            r1 = await http_client.get("/api/tiles/3/6/7")
            etag = r1.headers["etag"]
            r2 = await http_client.get("/api/tiles/3/6/7", headers={"If-None-Match": etag})

        assert r1.status_code == 200
        assert r2.status_code == 304
        assert r2.content == b""
        mreq.get.assert_called_once()  # 304 path never re-fetches upstream

    async def test_stale_etag_returns_full_200(self, http_client):
        import openosint.web_server as ws

        ws._tile_cache.clear()
        mock_resp = _mock_requests_response(status_code=200)
        mock_resp.content = b"\xff\xd8\xff\xe0fakejpeg"
        with patch("openosint.web_server._requests") as mreq:
            mreq.get.return_value = mock_resp
            r = await http_client.get("/api/tiles/3/6/1", headers={"If-None-Match": '"stale-etag"'})

        assert r.status_code == 200
        assert r.content == b"\xff\xd8\xff\xe0fakejpeg"

    async def test_tile_bucket_is_separate_from_keyless_tool_bucket(self, http_client):
        """A globe pan (tile requests) must never 429 a keyless tool call
        sharing the same client IP, and vice versa — separate buckets."""
        from openosint.web_server import _RL_MAX_REQS
        import openosint.web_server as ws

        ws._tile_cache.clear()
        ws._TILE_RATE_STORE.clear()
        ws._RATE_STORE.clear()

        async def fake_whois(domain, timeout_seconds=15):
            return "ok"

        mock_resp = _mock_requests_response(status_code=200)
        mock_resp.content = b"jpegbytes"

        with patch("openosint.web_server._requests") as mreq, \
             patch("openosint.web_server.run_whois_osint", new=fake_whois):
            mreq.get.return_value = mock_resp
            # Exhaust the keyless-tool bucket completely.
            tool_statuses = []
            for _ in range(_RL_MAX_REQS + 1):
                r = await http_client.post("/api/run/search_whois", json={"input": "example.com"})
                tool_statuses.append(r.status_code)

            # A tile request from the same client must still succeed — proves
            # the tile bucket wasn't touched by exhausting the tool bucket.
            tile_r = await http_client.get("/api/tiles/3/6/6")

        assert tool_statuses[-1] == 429  # tool bucket genuinely exhausted
        assert tile_r.status_code == 200  # tile bucket unaffected


# ---------------------------------------------------------------------------
# api_keys absent from logs (unconditional)
# ---------------------------------------------------------------------------


class TestDemoMode:
    """OPENOSINT_DEMO_MODE=true: /api/health exposes flag; /api/chat is blocked server-side."""

    @pytest_asyncio.fixture
    async def demo_client(self):
        """Simulates a process bound to 0.0.0.0 — a non-loopback bind, which
        is what actually drives DEMO_MODE now (see TestDemoModeFailsClosed)."""
        import openosint.web_server as ws
        from openosint.web_server import _RATE_STORE
        _RATE_STORE.clear()
        app = ws.create_app(host="0.0.0.0")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
        _RATE_STORE.clear()

    async def test_health_exposes_demo_mode_true(self, demo_client):
        resp = await demo_client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["demo_mode"] is True

    async def test_health_demo_mode_false_when_explicitly_disabled(self, http_client):
        """http_client pins DEMO_MODE False (see fixture) — this is NOT the
        real default; see TestDemoModeFailsClosed for the fail-closed default."""
        resp = await http_client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["demo_mode"] is False

    async def test_chat_returns_demo_block_not_backend(self, demo_client):
        """POST /api/chat in demo mode returns a structured SSE error and
        never calls _select_chat_backend."""
        called = []

        def spy_select(req):
            called.append(req)
            return "claude"

        with patch("openosint.web_server._select_chat_backend", side_effect=spy_select):
            resp = await demo_client.post(
                "/api/chat",
                json={"message": "investigate 8.8.8.8"},
            )

        assert resp.status_code == 200
        assert len(called) == 0, "_select_chat_backend must not be called in demo mode"
        body = resp.text
        assert '"type": "error"' in body
        assert "not bound to loopback" in body.lower()
        assert '"type": "done"' in body

    # -- Exposure A: no operator-keyed lookup may run for an anonymous demo caller --

    async def test_credentialed_tool_blocked_on_operator_key_in_demo_mode(
        self, demo_client, monkeypatch
    ):
        """A credentialed tool must not fall back to the operator's own env-var
        key while demo mode is active — the runner must never even be called."""
        monkeypatch.setenv("IPINFO_TOKEN", "operator-secret-token")
        called = []

        async def fake_ip(ip, timeout_seconds=30, *, api_key=None):
            called.append(api_key)
            return "should never run"

        with patch("openosint.web_server.run_ip_osint", new=fake_ip):
            resp = await demo_client.post("/api/run/search_ip", json={"input": "8.8.8.8"})

        assert resp.status_code == 200
        body = resp.json()
        assert body.get("key_required") is True
        assert "IPINFO_TOKEN" in body.get("missing_keys", [])
        assert called == [], "operator's key must never reach the tool runner in demo mode"

    async def test_credentialed_tool_runs_with_visitor_supplied_key_in_demo_mode(
        self, demo_client, monkeypatch
    ):
        """BYOK still works in demo mode — only the operator's own key is blocked."""
        monkeypatch.delenv("IPINFO_TOKEN", raising=False)
        received = []

        async def fake_ip(ip, timeout_seconds=30, *, api_key=None):
            received.append(api_key)
            return "ok"

        with patch("openosint.web_server.run_ip_osint", new=fake_ip):
            resp = await demo_client.post(
                "/api/run/search_ip",
                json={"input": "8.8.8.8", "api_keys": {"IPINFO_TOKEN": "visitor-own-key"}},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert received == ["visitor-own-key"]

    async def test_breach_lookup_blocked_in_demo_mode_even_with_visitor_key(
        self, demo_client, monkeypatch
    ):
        """Breach/HIBP is off in demo mode unconditionally — BYOK does not
        reopen it, because the data-controller concern isn't about whose key
        is used. No flag exists to turn this back on; it's a hard block."""
        monkeypatch.setenv("HIBP_API_KEY", "operator-secret-token")
        called = []

        async def fake_breach(email, timeout_seconds=30, *, api_key=None):
            called.append(api_key)
            return "should never run"

        with patch("openosint.web_server.run_breach_osint", new=fake_breach):
            resp = await demo_client.post(
                "/api/run/search_breach",
                json={
                    "input": "target@example.com",
                    "api_keys": {"HIBP_API_KEY": "visitor-own-key"},
                },
            )

        assert resp.status_code == 403
        assert called == [], "breach lookups must never run in demo mode, BYOK or not"

    async def test_stream_endpoint_blocked_for_credentialed_tool_in_demo_mode(
        self, demo_client, monkeypatch
    ):
        """/api/stream/{tool} has no BYOK parameter at all, so in demo mode it
        must refuse credentialed tools outright rather than silently falling
        back to the operator's key."""
        monkeypatch.setenv("SHODAN_API_KEY", "operator-secret-token")
        called = []

        async def fake_shodan(query, timeout_seconds=30, *, api_key=None):
            called.append(api_key)
            return "should never run"

        with patch("openosint.web_server.run_shodan_osint", new=fake_shodan):
            async with demo_client.stream(
                "GET", "/api/stream/search_shodan", params={"input": "8.8.8.8"}
            ) as resp:
                assert resp.status_code == 200
                body = b"".join([chunk async for chunk in resp.aiter_bytes()]).decode()

        assert called == [], "operator's key must never reach the tool runner in demo mode"
        assert "disabled" in body.lower() or "api key" in body.lower()

    async def test_keyless_tool_still_works_in_demo_mode(self, demo_client):
        """Tools with no operator credential (search_dns, search_domain, etc.)
        are unaffected by demo mode — Exposure A is about operator-held keys."""

        async def fake_dns(domain, timeout_seconds=15):
            return "ok"

        with patch("openosint.web_server.run_dns_osint", new=fake_dns):
            resp = await demo_client.post("/api/run/search_dns", json={"input": "example.com"})

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestDemoModeFailsClosed:
    """DEMO_MODE is a network-exposure invariant: driven by bind address, with
    OPENOSINT_DEMO_MODE only able to tighten it further, never loosen it. A
    self-hosted install bound to loopback must never be punished for an unset
    env var — that was the bug this replaced."""

    # -- bind address is the primary signal --

    def test_loopback_ipv4_is_not_restricted(self, monkeypatch):
        monkeypatch.delenv("OPENOSINT_DEMO_MODE", raising=False)
        import openosint.web_server as ws
        assert ws._compute_demo_mode("127.0.0.1") is False

    def test_localhost_is_not_restricted(self, monkeypatch):
        monkeypatch.delenv("OPENOSINT_DEMO_MODE", raising=False)
        import openosint.web_server as ws
        assert ws._compute_demo_mode("localhost") is False

    def test_loopback_ipv6_is_not_restricted(self, monkeypatch):
        monkeypatch.delenv("OPENOSINT_DEMO_MODE", raising=False)
        import openosint.web_server as ws
        assert ws._compute_demo_mode("::1") is False

    def test_wildcard_bind_is_restricted(self, monkeypatch):
        monkeypatch.delenv("OPENOSINT_DEMO_MODE", raising=False)
        import openosint.web_server as ws
        assert ws._compute_demo_mode("0.0.0.0") is True

    def test_explicit_external_address_is_restricted(self, monkeypatch):
        monkeypatch.delenv("OPENOSINT_DEMO_MODE", raising=False)
        import openosint.web_server as ws
        assert ws._compute_demo_mode("203.0.113.5") is True

    def test_undeterminable_bind_fails_closed_to_restricted(self, monkeypatch):
        """create_app() called with no host (e.g. a raw uvicorn --factory
        target bypassing serve_async()/run_server()) must not default open."""
        monkeypatch.delenv("OPENOSINT_DEMO_MODE", raising=False)
        import openosint.web_server as ws
        assert ws._compute_demo_mode(None) is True

    # -- OPENOSINT_DEMO_MODE can only tighten, never loosen --

    def test_env_var_forces_restriction_even_on_loopback(self, monkeypatch):
        monkeypatch.setenv("OPENOSINT_DEMO_MODE", "true")
        import openosint.web_server as ws
        assert ws._compute_demo_mode("127.0.0.1") is True

    def test_env_var_cannot_loosen_a_public_bind(self, monkeypatch):
        monkeypatch.setenv("OPENOSINT_DEMO_MODE", "false")
        import openosint.web_server as ws
        assert ws._compute_demo_mode("0.0.0.0") is True

    def test_malformed_env_var_adds_no_restriction_of_its_own(self, monkeypatch):
        """Safety no longer depends on this var's parsing — a garbage value
        on a loopback bind stays unrestricted; the bind address is what
        fails closed, not this variable (see test_undeterminable_bind_..)."""
        monkeypatch.setenv("OPENOSINT_DEMO_MODE", "yes please")
        import openosint.web_server as ws
        assert ws._compute_demo_mode("127.0.0.1") is False

    # -- create_app(host=...) actually applies the computation --

    def test_create_app_sets_demo_mode_from_host(self, monkeypatch):
        monkeypatch.delenv("OPENOSINT_DEMO_MODE", raising=False)
        import openosint.web_server as ws
        ws.create_app(host="127.0.0.1")
        assert ws.DEMO_MODE is False
        ws.create_app(host="0.0.0.0")
        assert ws.DEMO_MODE is True


class TestProxyExposureInvariant:
    """A loopback bind behind an on-host reverse proxy is publicly reachable
    even though nothing at the TCP layer distinguishes it from a direct local
    connection — GHSA-cqr4-hcfp-m6m4's exact concern, extended from
    /api/setup to every credentialed-tool and chat gate. See
    _request_restriction() and .claude/LEGAL_CONTEXT.md §8."""

    @pytest_asyncio.fixture
    async def loopback_client(self, monkeypatch):
        import openosint.web_server as ws
        monkeypatch.delenv("OPENOSINT_TRUSTED_PROXY", raising=False)
        monkeypatch.delenv("OPENOSINT_DEMO_MODE", raising=False)
        ws._RATE_STORE.clear()
        app = ws.create_app(host="127.0.0.1")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
        ws._RATE_STORE.clear()

    async def test_direct_loopback_is_not_restricted(self, loopback_client):
        resp = await loopback_client.get("/api/health")
        body = resp.json()
        assert body["restricted"] is False
        assert body["restriction_reason"] is None

    async def test_loopback_behind_undeclared_proxy_is_restricted(self, loopback_client):
        resp = await loopback_client.get(
            "/api/health", headers={"X-Forwarded-For": "203.0.113.9"}
        )
        body = resp.json()
        assert body["restricted"] is True
        assert "trusted-proxy" in body["restriction_reason"]

    async def test_loopback_behind_declared_trusted_proxy_is_not_restricted(
        self, loopback_client, monkeypatch
    ):
        monkeypatch.setattr("openosint.web_server.OPENOSINT_TRUSTED_PROXY", True)
        resp = await loopback_client.get(
            "/api/health", headers={"X-Forwarded-For": "203.0.113.9"}
        )
        body = resp.json()
        assert body["restricted"] is False

    async def test_conflicting_forwarded_proto_restricted_even_with_declared_trust(
        self, loopback_client, monkeypatch
    ):
        """Trust in the proxy doesn't extend to trusting headers that
        disagree with themselves — that's still treated as spoofing."""
        monkeypatch.setattr("openosint.web_server.OPENOSINT_TRUSTED_PROXY", True)
        resp = await loopback_client.get(
            "/api/health", headers={"X-Forwarded-Proto": "https, http"}
        )
        body = resp.json()
        assert body["restricted"] is True
        assert "inconsistent" in body["restriction_reason"]

    async def test_conflicting_forwarded_host_restricted(self, loopback_client):
        resp = await loopback_client.get(
            "/api/health", headers={"X-Forwarded-Host": "a.example.com, b.example.com"}
        )
        assert resp.json()["restricted"] is True

    async def test_credentialed_tool_blocked_behind_undeclared_proxy(
        self, loopback_client, monkeypatch
    ):
        """Prove the invariant actually gates tool access, not just /api/health's
        reporting: a locally-held key must not reach the runner."""
        monkeypatch.setenv("IPINFO_TOKEN", "locally-held-token")
        called = []

        async def fake_ip(ip, timeout_seconds=30, *, api_key=None):
            called.append(api_key)
            return "should never run"

        with patch("openosint.web_server.run_ip_osint", new=fake_ip):
            resp = await loopback_client.post(
                "/api/run/search_ip",
                json={"input": "8.8.8.8"},
                headers={"X-Forwarded-For": "203.0.113.9"},
            )

        assert resp.status_code == 200
        assert resp.json().get("key_required") is True
        assert called == [], "locally-held key must never reach the tool runner"

    async def test_startup_warning_logged_once_for_undeclared_proxy(
        self, loopback_client, monkeypatch, caplog
    ):
        import logging as _logging
        import openosint.web_server as ws

        monkeypatch.setattr(ws, "_proxy_warning_emitted", False)
        with caplog.at_level(_logging.WARNING):
            await loopback_client.get("/api/health", headers={"X-Forwarded-For": "203.0.113.9"})
            await loopback_client.get("/api/health", headers={"X-Forwarded-For": "203.0.113.9"})

        warnings = [r for r in caplog.records if "OPENOSINT_TRUSTED_PROXY" in r.getMessage()]
        assert len(warnings) == 1, "the warning must fire once, not on every request"


class TestCreateAppFactoryRoutes:
    """Verify create_app() is fully self-serving — no CLI wrapper required."""

    @pytest_asyncio.fixture
    async def factory_client(self):
        from openosint.web_server import create_app, _RATE_STORE

        _RATE_STORE.clear()
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
        _RATE_STORE.clear()

    async def test_root_returns_html(self, factory_client):
        resp = await factory_client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert resp.text.lstrip().startswith("<!DOCTYPE html>")

    async def test_static_mount_serves_file(self, factory_client):
        resp = await factory_client.get("/static/config.js")
        assert resp.status_code == 200

    async def test_health_demo_mode_flag(self):
        import openosint.web_server as ws
        from openosint.web_server import _RATE_STORE

        _RATE_STORE.clear()
        app = ws.create_app(host="0.0.0.0")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["demo_mode"] is True


class TestSetupEndpointGuards:
    """GHSA-cqr4-hcfp-m6m4: /api/setup must reject remote callers, unknown
    keys, and malformed *_BASE_URL values."""

    async def test_loopback_caller_can_save_allowlisted_key(self, http_client, tmp_path, monkeypatch):
        import openosint.web_server as ws

        monkeypatch.setattr(ws, "_ROOT", tmp_path)
        resp = await http_client.post("/api/setup", json={"SHODAN_API_KEY": "abc123"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["applied"] == ["SHODAN_API_KEY"]
        assert os.environ.get("SHODAN_API_KEY") == "abc123"
        os.environ.pop("SHODAN_API_KEY", None)

    async def test_remote_caller_is_rejected_before_body_is_applied(self, tmp_path, monkeypatch):
        import openosint.web_server as ws

        monkeypatch.setattr(ws, "_ROOT", tmp_path)
        app = ws.create_app()
        transport = ASGITransport(app=app, client=("203.0.113.5", 12345))
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/setup", json={"OPENAI_BASE_URL": "http://attacker.example/v1"})

        assert resp.status_code == 403
        assert "OPENAI_BASE_URL" not in os.environ
        assert not (tmp_path / ".env").exists()

    async def test_remote_caller_with_no_token_configured_is_rejected(self, tmp_path, monkeypatch):
        """No OPENOSINT_SETUP_TOKEN set → remote setup stays off, even with a header."""
        import openosint.web_server as ws

        monkeypatch.setattr(ws, "_ROOT", tmp_path)
        monkeypatch.delenv("OPENOSINT_SETUP_TOKEN", raising=False)
        app = ws.create_app()
        transport = ASGITransport(app=app, client=("203.0.113.5", 12345))
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/setup",
                json={"SHODAN_API_KEY": "x"},
                headers={"X-Setup-Token": "guessed-token"},
            )

        assert resp.status_code == 403
        assert "SHODAN_API_KEY" not in os.environ

    async def test_remote_caller_with_wrong_token_is_rejected(self, tmp_path, monkeypatch):
        import openosint.web_server as ws

        monkeypatch.setattr(ws, "_ROOT", tmp_path)
        monkeypatch.setenv("OPENOSINT_SETUP_TOKEN", "correct-token")
        app = ws.create_app()
        transport = ASGITransport(app=app, client=("203.0.113.5", 12345))
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/setup",
                json={"SHODAN_API_KEY": "x"},
                headers={"X-Setup-Token": "wrong-token"},
            )

        assert resp.status_code == 403
        assert "SHODAN_API_KEY" not in os.environ

    async def test_remote_caller_with_correct_token_is_accepted(self, tmp_path, monkeypatch):
        import openosint.web_server as ws

        monkeypatch.setattr(ws, "_ROOT", tmp_path)
        monkeypatch.setenv("OPENOSINT_SETUP_TOKEN", "correct-token")
        app = ws.create_app()
        transport = ASGITransport(app=app, client=("203.0.113.5", 12345))
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/setup",
                json={"SHODAN_API_KEY": "x"},
                headers={"X-Setup-Token": "correct-token"},
            )

        assert resp.status_code == 200
        assert resp.json()["applied"] == ["SHODAN_API_KEY"]
        os.environ.pop("SHODAN_API_KEY", None)

    async def test_non_allowlisted_key_is_dropped_not_written(self, http_client, tmp_path, monkeypatch):
        import openosint.web_server as ws

        monkeypatch.setattr(ws, "_ROOT", tmp_path)
        resp = await http_client.post("/api/setup", json={"NOT_A_REAL_ENV_VAR": "x"})

        assert resp.status_code == 200
        assert resp.json()["rejected"] == ["NOT_A_REAL_ENV_VAR"]
        assert "NOT_A_REAL_ENV_VAR" not in os.environ

    async def test_malformed_base_url_is_rejected(self, http_client, tmp_path, monkeypatch):
        import openosint.web_server as ws

        monkeypatch.setattr(ws, "_ROOT", tmp_path)
        resp = await http_client.post("/api/setup", json={"OPENAI_BASE_URL": "javascript:alert(1)"})

        assert resp.status_code == 200
        assert resp.json()["rejected"] == ["OPENAI_BASE_URL"]
        assert "OPENAI_BASE_URL" not in os.environ


class TestRequireSafeBind:
    """GHSA-cqr4-hcfp-m6m4: non-loopback binds need an explicit opt-in."""

    def test_loopback_host_is_always_allowed(self):
        from openosint.web_server import _require_safe_bind

        _require_safe_bind("127.0.0.1", allow_remote=False)  # no raise

    def test_wildcard_bind_without_opt_in_raises(self, monkeypatch):
        from openosint.web_server import _require_safe_bind

        monkeypatch.delenv("OPENOSINT_ALLOW_REMOTE", raising=False)
        with pytest.raises(SystemExit):
            _require_safe_bind("0.0.0.0", allow_remote=False)

    def test_wildcard_bind_with_allow_remote_flag_passes(self):
        from openosint.web_server import _require_safe_bind

        _require_safe_bind("0.0.0.0", allow_remote=True)  # no raise

    def test_wildcard_bind_with_env_var_passes(self, monkeypatch):
        from openosint.web_server import _require_safe_bind

        monkeypatch.setenv("OPENOSINT_ALLOW_REMOTE", "1")
        _require_safe_bind("0.0.0.0", allow_remote=False)  # no raise


class TestApiKeysNotLogged:
    async def test_secret_key_absent_from_log_records(self, http_client, caplog):
        secret = "top-secret-key-abc123"

        async def fake_shodan(query, timeout_seconds=30, *, api_key=None):
            return "ok"

        with (
            patch("openosint.web_server.run_shodan_osint", new=fake_shodan),
            caplog.at_level(logging.DEBUG),
        ):
            await http_client.post(
                "/api/run/search_shodan",
                json={"input": "8.8.8.8", "api_keys": {"SHODAN_API_KEY": secret}},
            )

        for record in caplog.records:
            assert secret not in record.getMessage(), (
                f"Secret leaked in log: {record.getMessage()!r}"
            )
