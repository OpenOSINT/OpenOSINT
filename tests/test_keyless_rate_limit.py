"""Keyless-tool rate limiting covers the expensive tools and both run routes;
binary availability matches how the tools actually find their binaries."""

from __future__ import annotations

import os
import stat
import sys

import pytest
from httpx import ASGITransport, AsyncClient

import openosint.web_server as ws
from openosint.utils import find_binary

NEWLY_LIMITED = ["search_github", "search_email", "search_username", "search_domain"]


@pytest.fixture
def limited_app(monkeypatch):
    monkeypatch.setattr(ws, "_RATE_STORE", {})
    monkeypatch.setattr(ws, "_RL_MAX_REQS", 2)

    async def fake_runner(value, timeout, keys=None):
        return "ok"

    runners = {name: fake_runner for name in ws._KEYLESS_TOOLS}
    monkeypatch.setattr(ws, "_RUNNERS", {**ws._RUNNERS, **runners})
    # The binary-backed tools are only runnable when their binary exists.
    monkeypatch.setattr(ws, "_check_available", lambda meta: (True, None))
    return ws.create_app(host="127.0.0.1", port=8080)


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8080")


def test_binary_and_github_tools_are_in_the_limited_set():
    assert set(NEWLY_LIMITED) <= ws._KEYLESS_TOOLS


@pytest.mark.parametrize("tool", NEWLY_LIMITED)
async def test_run_route_returns_429_after_the_limit(limited_app, tool):
    async with _client(limited_app) as c:
        codes = [(await c.post(f"/api/run/{tool}", json={"input": "x"})).status_code for _ in range(3)]

    assert codes == [200, 200, 429]


@pytest.mark.parametrize("tool", ["search_whois", *NEWLY_LIMITED])
async def test_stream_route_is_limited_too(limited_app, tool):
    async with _client(limited_app) as c:
        bodies = [(await c.get(f"/api/stream/{tool}", params={"input": "x"})).text for _ in range(3)]

    assert "Rate limit exceeded" not in bodies[0]
    assert "Rate limit exceeded" not in bodies[1]
    assert "Rate limit exceeded" in bodies[2]


async def test_credentialed_tools_are_not_counted_against_the_keyless_budget(limited_app):
    async with _client(limited_app) as c:
        for _ in range(5):
            resp = await c.post("/api/run/search_shodan", json={"input": "8.8.8.8"})

    assert resp.status_code != 429


@pytest.mark.skipif(os.name != "posix", reason="uses a POSIX executable bit")
def test_binaries_next_to_the_interpreter_are_found_without_being_on_path(tmp_path, monkeypatch):
    bin_dir = tmp_path / "env" / "bin"
    bin_dir.mkdir(parents=True)
    script = bin_dir / "holehe"
    script.write_text("#!/bin/sh\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(sys, "executable", str(bin_dir / "python"))
    monkeypatch.setenv("PATH", "/nonexistent")

    assert find_binary("holehe") == str(script)
    available, reason = ws._check_available({"requires_binary": ["holehe"]})
    assert available is True and reason is None


def test_missing_binary_message_gives_the_exact_install_command(monkeypatch):
    monkeypatch.setattr(ws, "find_binary", lambda _name: None)
    meta = next(m for m in ws._TOOL_CATALOG if m["name"] == "search_username")

    available, reason = ws._check_available(meta)

    assert available is False
    assert "sherlock is not installed" in reason
    assert "uv tool install sherlock-project" in reason
