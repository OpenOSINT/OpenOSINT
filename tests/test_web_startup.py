"""`openosint web` startup: bind first, then announce; busy port fails clearly."""

import asyncio
import io
import socket
import sys

import pytest

from openosint import web_server


@pytest.fixture
def busy_port():
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    yield blocker.getsockname()[1]
    blocker.close()


def test_bind_socket_returns_bound_socket_on_free_port():
    sock = web_server._bind_socket("127.0.0.1", 0)
    try:
        assert sock.getsockname()[1] != 0
    finally:
        sock.close()


def test_bind_socket_on_busy_port_exits_with_port_hint(busy_port):
    with pytest.raises(SystemExit) as exc:
        web_server._bind_socket("127.0.0.1", busy_port)

    message = str(exc.value)
    assert f"Port {busy_port} is already in use" in message
    assert f"openosint web --port {busy_port + 1}" in message


def test_serve_async_on_busy_port_prints_no_url_and_skips_browser(busy_port, capsys):
    opened = []

    with pytest.raises(SystemExit):
        asyncio.run(web_server.serve_async(port=busy_port, on_started=lambda: opened.append(1)))

    assert "http://" not in capsys.readouterr().out
    assert opened == []


def test_banner_shows_data_dir_and_no_key_notice(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OPENOSINT_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    web_server._print_banner("127.0.0.1", 8080)

    out = capsys.readouterr().out
    assert "http://127.0.0.1:8080/" in out
    assert str(tmp_path / "data") in out
    assert "No AI provider configured" in out


def test_banner_omits_no_key_notice_when_key_present(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    web_server._print_banner("127.0.0.1", 8080)

    assert "No AI provider configured" not in capsys.readouterr().out


def test_banner_survives_a_stdout_that_cannot_encode_the_arrow(monkeypatch):
    """Windows with stdout redirected defaults to cp1252, which has no '→'."""
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252", write_through=True)
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    web_server._print_banner("127.0.0.1", 8080)

    assert b"http://127.0.0.1:8080/" in buffer.getvalue()
