"""Native HTTP transport: real MCP requests with no external OSINT traffic."""

from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings, strategies as st
from starlette.testclient import TestClient

from openosint import __version__, mcp_server
from openosint.mcp_http import create_http_app, read_http_token

TOKEN = "test-inbound-key-with-enough-entropy"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}


@pytest.fixture(autouse=True)
def passive(monkeypatch):
    monkeypatch.delenv("OPENOSINT_ALLOW_ACTIVE", raising=False)
    monkeypatch.delenv("OPENOSINT_MCP_TOKEN", raising=False)
    monkeypatch.delenv("OPENOSINT_MCP_TOKEN_FILE", raising=False)


def rpc(client, method, params=None):
    response = client.post(
        "/mcp",
        headers=HEADERS,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()["result"]


def test_http_initialization_tools_and_passive_call(monkeypatch):
    lookup = AsyncMock(return_value="DNS fixture for example.com")
    monkeypatch.setattr(mcp_server, "run_dns_osint", lookup)
    with TestClient(
        create_http_app(mcp_server.app, token=TOKEN), base_url="http://localhost"
    ) as client:
        result = rpc(
            client,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        assert result["serverInfo"] == {"name": "openosint", "version": __version__}
        tools = rpc(client, "tools/list")["tools"]
        assert {tool["name"] for tool in tools} == {
            tool.name for tool in mcp_server._all_tools() if mcp_server.is_tool_enabled(tool.name)
        }
        assert "scrape_url" not in {tool["name"] for tool in tools}
        result = rpc(
            client, "tools/call", {"name": "search_dns", "arguments": {"domain": "example.com"}}
        )
        assert result["content"][0]["text"] == "DNS fixture for example.com"
        lookup.assert_awaited_once()
        result = rpc(
            client,
            "tools/call",
            {"name": "scrape_url", "arguments": {"url": "https://example.com"}},
        )
        assert "disabled_in_passive_mode" in result["content"][0]["text"]


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
@pytest.mark.parametrize(
    "authorization", [None, "Bearer wrong", "Basic abc", "Bearer", "Bearer " + TOKEN + " extra"]
)
def test_authentication_guards_every_mcp_method(method, authorization):
    headers = {} if authorization is None else {"Authorization": authorization}
    with TestClient(
        create_http_app(mcp_server.app, token=TOKEN), base_url="http://localhost"
    ) as client:
        response = client.request(method, "/mcp", headers=headers)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert TOKEN not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/health").json() == {"status": "ok"}


def test_duplicate_headers_and_foreign_host_or_origin():
    with TestClient(
        create_http_app(mcp_server.app, token=TOKEN), base_url="http://localhost"
    ) as client:
        duplicate = [("Authorization", f"Bearer {TOKEN}")] * 2
        assert client.get("/mcp", headers=duplicate).status_code == 401
        assert client.get("/mcp", headers={**HEADERS, "Host": "evil.example"}).status_code == 421
        assert (
            client.get("/mcp", headers={**HEADERS, "Origin": "https://evil.example"}).status_code
            == 403
        )
        assert (
            client.delete(
                "/mcp", headers={**HEADERS, "Authorization": f"bEaReR {TOKEN}"}
            ).status_code
            != 401
        )


@given(
    st.text(
        alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=1, max_size=80
    ).filter(lambda value: value != TOKEN)
)
@settings(max_examples=50, deadline=None)
def test_arbitrary_wrong_bearers_never_authorize(supplied):
    with TestClient(
        create_http_app(mcp_server.app, token=TOKEN), base_url="http://localhost"
    ) as client:
        assert (
            client.get("/mcp", headers={"Authorization": f"Bearer {supplied}"}).status_code == 401
        )


def test_loopback_without_token_and_explicit_docker_hostname():
    with TestClient(create_http_app(mcp_server.app), base_url="http://localhost") as client:
        assert client.get("/mcp").status_code != 401
    with pytest.raises(ValueError, match="bearer"):
        create_http_app(mcp_server.app, host="0.0.0.0")
    with TestClient(
        create_http_app(
            mcp_server.app, host="0.0.0.0", token=TOKEN, allowed_hosts=["openosint-mcp:8081"]
        ),
        base_url="http://openosint-mcp:8081",
    ) as client:
        assert client.delete("/mcp", headers=HEADERS).status_code != 421


def test_token_sources_and_fail_closed(monkeypatch, tmp_path):
    assert read_http_token() is None
    monkeypatch.setenv("OPENOSINT_MCP_TOKEN", TOKEN)
    assert read_http_token() == TOKEN
    monkeypatch.setenv("CUSTOM_INBOUND_KEY", "custom-key")
    assert read_http_token(token_env="CUSTOM_INBOUND_KEY") == "custom-key"
    path = tmp_path / "token"
    path.write_text("file-key\n")
    path.chmod(0o600)
    monkeypatch.setenv("OPENOSINT_MCP_TOKEN_FILE", str(path))
    assert read_http_token() == "file-key"
    assert read_http_token(token_file=str(path), token_env="MISSING") == "file-key"
    with pytest.raises(ValueError, match="empty or unset"):
        read_http_token(token_env="MISSING")
    path.write_text("\n")
    with pytest.raises(ValueError, match="empty"):
        read_http_token()
    with pytest.raises(ValueError, match="read"):
        read_http_token(token_file=str(tmp_path / "missing"))


@pytest.mark.parametrize("token", ["key with spaces", "key\nsecond-key", "非ASCII"])
def test_invalid_token_never_leaks_in_error(monkeypatch, token):
    monkeypatch.setenv("OPENOSINT_MCP_TOKEN", token)
    with pytest.raises(ValueError) as error:
        read_http_token()
    assert token not in str(error.value)


def test_file_permissions_and_size(tmp_path):
    import os

    path = tmp_path / "token"
    path.write_text(TOKEN)
    if os.name == "posix":
        path.chmod(0o644)
        with pytest.raises(ValueError, match="owner-only"):
            read_http_token(token_file=str(path))
    path.chmod(0o600)
    path.write_text("x" * 5000)
    with pytest.raises(ValueError, match="too large"):
        read_http_token(token_file=str(path))
    path.write_text(TOKEN + " " * 5000 + "another-key")
    with pytest.raises(ValueError, match="too large"):
        read_http_token(token_file=str(path))
    with pytest.raises(ValueError, match="regular file"):
        read_http_token(token_file=str(tmp_path))


@pytest.mark.parametrize("port", ["0", "-1", "65536"])
def test_invalid_http_ports_fail_before_serving(port):
    with pytest.raises(SystemExit) as error:
        mcp_server.main(["--http", "--port", port])
    assert error.value.code == 2


def test_non_loopback_without_token_fails_at_cli():
    with pytest.raises(SystemExit) as error:
        mcp_server.main(["--http", "--host", "0.0.0.0"])
    assert error.value.code == 2


def test_stdio_default_and_http_flag_validation(monkeypatch):
    serve = AsyncMock()
    monkeypatch.setattr(mcp_server, "_serve", serve)
    mcp_server.main([])
    serve.assert_awaited_once()
    for flags in (["--port", "8081"], ["--host", "0.0.0.0"], ["--http-token-env", "KEY"]):
        with pytest.raises(SystemExit) as error:
            mcp_server.main(flags)
        assert error.value.code == 2


def test_http_cli_starts_uvicorn_without_changing_passive_mode(monkeypatch):
    import uvicorn

    runs = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: runs.append((app, kwargs)))
    monkeypatch.setenv("OPENOSINT_MCP_TOKEN", TOKEN)
    mcp_server.main(
        [
            "--http",
            "--host",
            "0.0.0.0",
            "--port",
            "8081",
            "--http-allowed-host",
            "openosint-mcp:8081",
        ]
    )
    assert runs[0][1]["host"] == "0.0.0.0"
    assert runs[0][1]["port"] == 8081
    assert not mcp_server.is_tool_enabled("scrape_url")
