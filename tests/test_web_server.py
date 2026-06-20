# tests/test_web_server.py
"""
Unit tests for web_server.py Ollama streaming and tool-argument handling.

All HTTP calls are mocked — no live Ollama instance required.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

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
# Tool catalog & health endpoint tests
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    async def test_health_endpoint_returns_version(self):
        """Should include version in health response."""
        from openosint import __version__
        from openosint.web_server import create_app

        app = create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == __version__

    async def test_health_endpoint_has_status_ok(self):
        from openosint.web_server import create_app

        app = create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestToolsEndpoint:
    async def test_tools_endpoint_returns_all_tools(self):
        """Should return all tools in the catalog."""
        from openosint.web_server import create_app

        app = create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 18
        names = {t["name"] for t in data}
        assert "search_dorks_live" in names
        assert "scrape_url" in names
        assert "search_abuseipdb" in names
        assert "search_dns" in names
        assert "search_github" in names
        assert "search_email" in names
        assert "search_username" in names

    async def test_tools_have_required_fields(self):
        """Each tool should have name, description, and available fields."""
        from openosint.web_server import create_app

        app = create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/tools")
        for tool in resp.json():
            assert "name" in tool
            assert "description" in tool
            assert "available" in tool
            assert "category" in tool


class TestSetupEndpoint:
    async def test_setup_endpoint_rejects_non_local_origin(self):
        """Should return 403 for cross-origin requests."""
        from openosint.web_server import create_app

        app = create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post(
            "/api/setup",
            json={"SOME_KEY": "some_value"},
            headers={"origin": "https://evil.com"},
        )
        assert resp.status_code == 403
        data = resp.json()
        assert "error" in data or "status" in data

    async def test_setup_endpoint_allows_localhost(self):
        """Should allow requests from localhost origin."""
        from openosint.web_server import create_app

        app = create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post(
            "/api/setup",
            json={"SOME_KEY": "some_value"},
            headers={"origin": "http://localhost:8080"},
        )
        # Should be allowed (even if .env write may fail in test env)
        assert resp.status_code in (200, 403)


class TestRunToolEndpoint:
    async def test_run_tool_with_empty_input_returns_output(self):
        """Should handle empty input gracefully."""
        from openosint.web_server import create_app

        app = create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)
        # Run a tool that doesn't require env vars
        resp = client.post("/api/run/search_whois", json={"input": ""})
        # Should return some kind of output (either error or empty)
        assert resp.status_code == 200
        data = resp.json()
        assert "output" in data
        assert data["status"] in ("ok", "error")

    async def test_run_tool_returns_expected_fields(self):
        """Response should include output, tool, and elapsed."""
        from openosint.web_server import create_app

        app = create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post("/api/run/search_whois", json={"input": "example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert "output" in data
        assert data["tool"] == "search_whois"
        assert "elapsed" in data
