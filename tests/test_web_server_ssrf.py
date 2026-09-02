# tests/test_web_server_ssrf.py
"""
Regression tests for GHSA-q6cw-g86h-m2cq: /api/chat and /api/openai/test
coupled a request-supplied backend destination with an environment-sourced
credential, letting a caller redirect the server's OPENAI_API_KEY to an
attacker-controlled host (credential theft + SSRF).

Covers:
  - the env credential is never sent when the request supplies a base_url
  - client-supplied backends are rejected by default (OPENOSINT_ALLOW_CLIENT_BACKEND unset)
  - _validate_outbound_base_url's two-tier IP policy (amendment 2)
  - OPENOSINT_ALLOWED_BASE_URLS strict host allowlist override
  - the Sec-Fetch-Site / Origin browser guard (amendment 4)
  - redirects are disabled on every outbound call (amendment 3)
  - the default local-backend path (env-configured, no client base_url) still works
  - forcing "backend": "openai" leaks nothing when client backends are disabled

All HTTP calls are mocked — no live endpoint or network access required.
Follows the fixture and mocking conventions of test_web_server.py /
test_web_server_openai.py.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient


def _mock_requests_response(status_code: int = 200, body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    body = body or {}
    resp.text = json.dumps(body)[:300]
    resp.json.return_value = body
    return resp


@pytest_asyncio.fixture
async def client():
    """Loopback bind: these tests exercise chat-backend/SSRF behavior, not
    demo-mode gating (see test_web_server.py::TestDemoMode for that)."""
    import openosint.web_server as ws

    app = ws.create_app(host="127.0.0.1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Client-supplied backend rejected by default
# ---------------------------------------------------------------------------


class TestClientBackendDisabledByDefault:
    async def test_openai_base_url_in_chat_rejected_without_flag(self, client, monkeypatch):
        monkeypatch.delenv("OPENOSINT_ALLOW_CLIENT_BACKEND", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        resp = await client.post(
            "/api/chat",
            json={
                "message": "hi",
                "model": "openai",
                "openai_base_url": "http://attacker.example/v1",
                "openai_api_key": "",
            },
        )
        assert resp.status_code == 403

    async def test_openai_base_url_in_test_endpoint_rejected_without_flag(self, client, monkeypatch):
        monkeypatch.delenv("OPENOSINT_ALLOW_CLIENT_BACKEND", raising=False)

        resp = await client.post(
            "/api/openai/test",
            json={"openai_base_url": "http://attacker.example/v1", "openai_api_key": ""},
        )
        assert resp.status_code == 403

    async def test_client_supplied_ollama_host_rejected_without_flag(self, client, monkeypatch):
        monkeypatch.delenv("OPENOSINT_ALLOW_CLIENT_BACKEND", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

        resp = await client.post(
            "/api/chat",
            json={
                "message": "hi",
                "model": "ollama",
                "ollama_host": "http://10.0.0.9:11434",
            },
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Core fix: env credential never attached to a client-supplied destination
# ---------------------------------------------------------------------------


class TestEnvCredentialNeverLeaksToClientDestination:
    async def test_env_api_key_not_sent_when_request_base_url_and_empty_key(
        self, client, monkeypatch
    ):
        monkeypatch.setenv("OPENOSINT_ALLOW_CLIENT_BACKEND", "1")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "server-secret-key")

        body = {"choices": [{"message": {"content": "ok", "tool_calls": []}}]}
        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.return_value = _mock_requests_response(body=body)
                resp = await client.post(
                    "/api/chat",
                    json={
                        "message": "hi",
                        "model": "openai",
                        "openai_base_url": "http://127.0.0.1:9999/v1",
                        "openai_api_key": "",
                    },
                )

        assert resp.status_code == 200
        headers = mreq.post.call_args.kwargs["headers"]
        assert "Authorization" not in headers
        assert "server-secret-key" not in resp.text

    async def test_openai_test_endpoint_env_key_not_sent_to_client_base_url(
        self, client, monkeypatch
    ):
        monkeypatch.setenv("OPENOSINT_ALLOW_CLIENT_BACKEND", "1")
        monkeypatch.setenv("OPENAI_API_KEY", "server-secret-key")

        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.get.return_value = _mock_requests_response(status_code=200, body={"data": []})
                resp = await client.post(
                    "/api/openai/test",
                    json={"openai_base_url": "http://127.0.0.1:9999/v1", "openai_api_key": ""},
                )

        assert resp.status_code == 200
        headers = mreq.get.call_args.kwargs["headers"]
        assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# _validate_outbound_base_url — two-tier IP policy
# ---------------------------------------------------------------------------


class TestValidateOutboundBaseUrl:
    async def test_metadata_link_local_always_rejected(self):
        from openosint.web_server import _validate_outbound_base_url

        with pytest.raises(HTTPException) as exc:
            await _validate_outbound_base_url("http://169.254.169.254/latest/meta-data/")
        assert exc.value.status_code == 403

    async def test_ipv6_link_local_always_rejected(self):
        from openosint.web_server import _validate_outbound_base_url

        with pytest.raises(HTTPException) as exc:
            await _validate_outbound_base_url("http://[fe80::1]/v1")
        assert exc.value.status_code == 403

    async def test_loopback_permitted(self):
        from openosint.web_server import _validate_outbound_base_url

        result = await _validate_outbound_base_url("http://127.0.0.1:8080/v1")
        assert result == "http://127.0.0.1:8080/v1"

    async def test_rfc1918_10_permitted(self):
        from openosint.web_server import _validate_outbound_base_url

        result = await _validate_outbound_base_url("http://10.0.0.5:8080/v1")
        assert result == "http://10.0.0.5:8080/v1"

    async def test_rfc1918_192_168_permitted(self):
        from openosint.web_server import _validate_outbound_base_url

        result = await _validate_outbound_base_url("http://192.168.1.50:11434")
        assert result == "http://192.168.1.50:11434"

    async def test_file_scheme_rejected(self):
        from openosint.web_server import _validate_outbound_base_url

        with pytest.raises(HTTPException) as exc:
            await _validate_outbound_base_url("file:///etc/passwd")
        assert exc.value.status_code == 403

    async def test_gopher_scheme_rejected(self):
        from openosint.web_server import _validate_outbound_base_url

        with pytest.raises(HTTPException) as exc:
            await _validate_outbound_base_url("gopher://example.com")
        assert exc.value.status_code == 403

    async def test_userinfo_rejected(self):
        from openosint.web_server import _validate_outbound_base_url

        with pytest.raises(HTTPException) as exc:
            await _validate_outbound_base_url("http://user:pass@127.0.0.1:8080/v1")
        assert exc.value.status_code == 403

    async def test_multicast_rejected(self):
        from openosint.web_server import _validate_outbound_base_url

        with pytest.raises(HTTPException) as exc:
            await _validate_outbound_base_url("http://224.0.0.1/v1")
        assert exc.value.status_code == 403

    async def test_allowed_base_urls_env_permits_matching_host(self, monkeypatch):
        monkeypatch.setenv("OPENOSINT_ALLOWED_BASE_URLS", "trusted.internal:9000")
        from openosint.web_server import _validate_outbound_base_url

        result = await _validate_outbound_base_url("http://trusted.internal:9000/v1")
        assert result == "http://trusted.internal:9000/v1"

    async def test_allowed_base_urls_env_rejects_non_matching_host(self, monkeypatch):
        monkeypatch.setenv("OPENOSINT_ALLOWED_BASE_URLS", "trusted.internal:9000")
        from openosint.web_server import _validate_outbound_base_url

        with pytest.raises(HTTPException) as exc:
            await _validate_outbound_base_url("http://127.0.0.1:8080/v1")
        assert exc.value.status_code == 403

    async def test_allowed_base_urls_overrides_link_local_metadata_block(self, monkeypatch):
        """An operator who explicitly pins 169.254.169.254 has taken on that
        risk knowingly — the allowlist is a stricter, operator-chosen boundary
        that supersedes the IP-class checks, not a hole in them."""
        monkeypatch.setenv("OPENOSINT_ALLOWED_BASE_URLS", "169.254.169.254")
        from openosint.web_server import _validate_outbound_base_url

        result = await _validate_outbound_base_url("http://169.254.169.254/v1")
        assert result == "http://169.254.169.254/v1"


# ---------------------------------------------------------------------------
# 403 uniformity: flag-off, URL-validation-failure, and origin-guard
# rejections must be byte-identical — an oracle inside the oracle fix
# otherwise (a distinguishable message leaks whether
# OPENOSINT_ALLOW_CLIENT_BACKEND is enabled on this deployment).
# ---------------------------------------------------------------------------


class TestRejectionMessageUniformity:
    async def test_flag_off_vs_bad_scheme_with_flag_on_identical(self, client, monkeypatch):
        monkeypatch.delenv("OPENOSINT_ALLOW_CLIENT_BACKEND", raising=False)
        resp_off = await client.post(
            "/api/openai/test",
            json={"openai_base_url": "http://attacker.example/v1", "openai_api_key": ""},
        )

        monkeypatch.setenv("OPENOSINT_ALLOW_CLIENT_BACKEND", "1")
        resp_bad_scheme = await client.post(
            "/api/openai/test",
            json={"openai_base_url": "gopher://attacker.example/v1", "openai_api_key": ""},
        )

        assert resp_off.status_code == resp_bad_scheme.status_code == 403
        assert resp_off.json() == resp_bad_scheme.json()

    async def test_flag_off_vs_disallowed_ip_with_flag_on_identical(self, client, monkeypatch):
        monkeypatch.delenv("OPENOSINT_ALLOW_CLIENT_BACKEND", raising=False)
        resp_off = await client.post(
            "/api/openai/test",
            json={"openai_base_url": "http://169.254.169.254/v1", "openai_api_key": ""},
        )

        monkeypatch.setenv("OPENOSINT_ALLOW_CLIENT_BACKEND", "1")
        resp_metadata = await client.post(
            "/api/openai/test",
            json={"openai_base_url": "http://169.254.169.254/v1", "openai_api_key": ""},
        )

        assert resp_off.status_code == resp_metadata.status_code == 403
        assert resp_off.json() == resp_metadata.json()

    async def test_flag_off_vs_origin_guard_rejection_identical(self, client, monkeypatch):
        monkeypatch.delenv("OPENOSINT_ALLOW_CLIENT_BACKEND", raising=False)
        resp_off = await client.post(
            "/api/openai/test",
            json={"openai_base_url": "http://attacker.example/v1", "openai_api_key": ""},
        )

        monkeypatch.setenv("OPENOSINT_ALLOW_CLIENT_BACKEND", "1")
        resp_cross_site = await client.post(
            "/api/openai/test",
            json={"openai_base_url": "http://127.0.0.1:9999/v1"},
            headers={"Sec-Fetch-Site": "cross-site"},
        )

        assert resp_off.status_code == resp_cross_site.status_code == 403
        assert resp_off.json() == resp_cross_site.json()

    async def test_allowlist_mismatch_matches_flag_off_message(self, client, monkeypatch):
        monkeypatch.delenv("OPENOSINT_ALLOW_CLIENT_BACKEND", raising=False)
        resp_off = await client.post(
            "/api/openai/test",
            json={"openai_base_url": "http://attacker.example/v1", "openai_api_key": ""},
        )

        monkeypatch.setenv("OPENOSINT_ALLOW_CLIENT_BACKEND", "1")
        monkeypatch.setenv("OPENOSINT_ALLOWED_BASE_URLS", "trusted.internal:9000")
        resp_not_allowlisted = await client.post(
            "/api/openai/test",
            json={"openai_base_url": "http://127.0.0.1:9999/v1", "openai_api_key": ""},
        )

        assert resp_off.status_code == resp_not_allowlisted.status_code == 403
        assert resp_off.json() == resp_not_allowlisted.json()


# ---------------------------------------------------------------------------
# Sec-Fetch-Site / Origin browser guard — only active when the flag is set
# ---------------------------------------------------------------------------


class TestBrowserOriginGuard:
    async def test_sec_fetch_site_cross_site_rejected(self, client, monkeypatch):
        monkeypatch.setenv("OPENOSINT_ALLOW_CLIENT_BACKEND", "1")

        resp = await client.post(
            "/api/openai/test",
            json={"openai_base_url": "http://127.0.0.1:9999/v1"},
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        assert resp.status_code == 403

    async def test_sec_fetch_site_same_site_rejected(self, client, monkeypatch):
        monkeypatch.setenv("OPENOSINT_ALLOW_CLIENT_BACKEND", "1")

        resp = await client.post(
            "/api/openai/test",
            json={"openai_base_url": "http://127.0.0.1:9999/v1"},
            headers={"Sec-Fetch-Site": "same-site"},
        )
        assert resp.status_code == 403

    async def test_sec_fetch_site_same_origin_allowed(self, client, monkeypatch):
        monkeypatch.setenv("OPENOSINT_ALLOW_CLIENT_BACKEND", "1")

        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.get.return_value = _mock_requests_response(status_code=200, body={})
                resp = await client.post(
                    "/api/openai/test",
                    json={"openai_base_url": "http://127.0.0.1:9999/v1"},
                    headers={"Sec-Fetch-Site": "same-origin"},
                )
        assert resp.status_code == 200

    async def test_origin_mismatch_rejected(self, client, monkeypatch):
        monkeypatch.setenv("OPENOSINT_ALLOW_CLIENT_BACKEND", "1")

        resp = await client.post(
            "/api/openai/test",
            json={"openai_base_url": "http://127.0.0.1:9999/v1"},
            headers={"Origin": "https://attacker.example"},
        )
        assert resp.status_code == 403

    async def test_origin_match_allowed(self, client, monkeypatch):
        monkeypatch.setenv("OPENOSINT_ALLOW_CLIENT_BACKEND", "1")

        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.get.return_value = _mock_requests_response(status_code=200, body={})
                resp = await client.post(
                    "/api/openai/test",
                    json={"openai_base_url": "http://127.0.0.1:9999/v1"},
                    headers={"Origin": "http://test"},
                )
        assert resp.status_code == 200

    async def test_extra_allowed_origin_env_permits_reverse_proxy_host(self, client, monkeypatch):
        monkeypatch.setenv("OPENOSINT_ALLOW_CLIENT_BACKEND", "1")
        monkeypatch.setenv("OPENOSINT_ALLOWED_ORIGINS", "https://proxy.example")

        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.get.return_value = _mock_requests_response(status_code=200, body={})
                resp = await client.post(
                    "/api/openai/test",
                    json={"openai_base_url": "http://127.0.0.1:9999/v1"},
                    headers={"Origin": "https://proxy.example"},
                )
        assert resp.status_code == 200

    async def test_no_origin_headers_allowed_like_curl(self, client, monkeypatch):
        """Neither Sec-Fetch-Site nor Origin present (curl/SDK/script) — waved through."""
        monkeypatch.setenv("OPENOSINT_ALLOW_CLIENT_BACKEND", "1")

        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.get.return_value = _mock_requests_response(status_code=200, body={})
                resp = await client.post(
                    "/api/openai/test",
                    json={"openai_base_url": "http://127.0.0.1:9999/v1"},
                )
        assert resp.status_code == 200

    async def test_guard_inactive_when_flag_off(self, client, monkeypatch):
        """A cross-site Origin header must not block the ordinary env-only
        chat path when client-supplied backends are disabled — the guard
        only exists to protect the flag it's gating."""
        monkeypatch.delenv("OPENOSINT_ALLOW_CLIENT_BACKEND", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real-key")

        async def fake_stream(messages):
            yield {"type": "done"}

        with patch("openosint.web_server._stream_claude", side_effect=fake_stream):
            resp = await client.post(
                "/api/chat",
                json={"message": "hi"},
                headers={"Sec-Fetch-Site": "cross-site"},
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Redirects disabled on every outbound call (amendment 3)
# ---------------------------------------------------------------------------


class TestRedirectsDisabled:
    async def test_stream_openai_requests_fallback_disables_redirects(self):
        from openosint.web_server import _stream_openai

        body = {"choices": [{"message": {"content": "ok", "tool_calls": []}}]}
        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.return_value = _mock_requests_response(body=body)
                events = []
                async for e in _stream_openai(
                    [{"role": "user", "content": "hi"}], "http://localhost:4000/v1", "", "gpt-4o-mini"
                ):
                    events.append(e)

        assert mreq.post.call_args.kwargs.get("allow_redirects") is False

    async def test_probe_openai_endpoint_requests_fallback_disables_redirects(self):
        from openosint.web_server import _probe_openai_endpoint

        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.get.return_value = _mock_requests_response(status_code=200, body={})
                await _probe_openai_endpoint("http://localhost:4000/v1", "key")

        assert mreq.get.call_args.kwargs.get("allow_redirects") is False

    async def test_stream_ollama_requests_fallback_disables_redirects(self):
        from openosint.web_server import _stream_ollama

        body = {"message": {"content": "ok", "tool_calls": []}}
        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.return_value = _mock_requests_response(body=body)
                events = []
                async for e in _stream_ollama(
                    [{"role": "user", "content": "hi"}], "http://localhost:11434", "llama3.2"
                ):
                    events.append(e)

        assert mreq.post.call_args.kwargs.get("allow_redirects") is False

    async def test_stream_openai_httpx_disables_follow_redirects(self):
        from openosint.web_server import _stream_openai

        body = {"choices": [{"message": {"content": "ok", "tool_calls": []}}]}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = body
        mock_response.text = ""

        mock_httpx = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_httpx.AsyncClient.return_value = mock_client_instance

        with patch("openosint.web_server._httpx", mock_httpx):
            events = []
            async for e in _stream_openai(
                [{"role": "user", "content": "hi"}], "http://localhost:4000/v1", "", "gpt-4o-mini"
            ):
                events.append(e)

        assert mock_httpx.AsyncClient.call_args.kwargs.get("follow_redirects") is False


# ---------------------------------------------------------------------------
# Default local-backend path (env-configured) still works
# ---------------------------------------------------------------------------


class TestDefaultLocalBackendStillWorks:
    async def test_env_configured_openai_base_url_used_without_client_backend_flag(
        self, client, monkeypatch
    ):
        monkeypatch.delenv("OPENOSINT_ALLOW_CLIENT_BACKEND", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8080/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "local-key")

        body = {"choices": [{"message": {"content": "hello", "tool_calls": []}}]}
        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.return_value = _mock_requests_response(body=body)
                resp = await client.post(
                    "/api/chat",
                    json={"message": "hi", "model": "claude"},
                )

        assert resp.status_code == 200
        assert '"type": "text"' in resp.text
        # The default local backend legitimately uses its own env key.
        headers = mreq.post.call_args.kwargs["headers"]
        assert headers.get("Authorization") == "Bearer local-key"

    async def test_ollama_default_host_from_env_not_gated(self, client, monkeypatch):
        """A UI that mirrors /api/health's ollama_host back in the request
        must not be gated — it matches the server's own configured default."""
        monkeypatch.delenv("OPENOSINT_ALLOW_CLIENT_BACKEND", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")

        body = {"message": {"content": "hello", "tool_calls": []}}
        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                mreq.post.return_value = _mock_requests_response(body=body)
                resp = await client.post(
                    "/api/chat",
                    json={
                        "message": "hi",
                        "model": "ollama",
                        "ollama_host": "http://localhost:11434",
                    },
                )

        assert resp.status_code == 200

    async def test_shipped_ui_payload_empty_openai_fields_uses_env_backend(
        self, client, monkeypatch
    ):
        """_sendMessageServerSide (openosint/web/index.html) sends this exact
        body on every message — openai_base_url/openai_api_key/openai_model
        default to '' and are always included, never omitted. With the flag
        unset, these empty strings must be treated as "not supplied" (a
        truthiness check, not `is not None` and not field-presence) so the
        shipped UI's default Claude/env-configured flow keeps working."""
        monkeypatch.delenv("OPENOSINT_ALLOW_CLIENT_BACKEND", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real-key")

        async def fake_stream(messages):
            yield {"type": "text", "content": "hello"}
            yield {"type": "done"}

        shipped_ui_payload = {
            "message": "investigate 8.8.8.8",
            "history": [],
            "model": "claude",
            "ollama_model": "llama3.2",
            "ollama_host": "http://localhost:11434",
            "openai_base_url": "",
            "openai_model": "",
            "openai_api_key": "",
        }

        with patch("openosint.web_server._stream_claude", side_effect=fake_stream):
            resp = await client.post("/api/chat", json=shipped_ui_payload)

        assert resp.status_code == 200
        assert '"type": "text"' in resp.text
        assert '"type": "done"' in resp.text


# ---------------------------------------------------------------------------
# Forcing "backend": "openai" leaks nothing when client backends are disabled
# ---------------------------------------------------------------------------


class TestForcingBackendLeaksNothing:
    async def test_forced_openai_backend_with_attacker_url_makes_no_outbound_call(
        self, client, monkeypatch
    ):
        monkeypatch.delenv("OPENOSINT_ALLOW_CLIENT_BACKEND", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8080/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "server-secret-key")

        with patch("openosint.web_server._httpx", None):
            with patch("openosint.web_server._requests") as mreq:
                resp = await client.post(
                    "/api/chat",
                    json={
                        "message": "hi",
                        "model": "openai",
                        "openai_base_url": "http://attacker.example/v1",
                        "openai_api_key": "",
                    },
                )
                mreq.post.assert_not_called()

        assert resp.status_code == 403
        assert "server-secret-key" not in resp.text
