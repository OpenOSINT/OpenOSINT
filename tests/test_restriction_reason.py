"""The reported restriction reason must be the real one."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import openosint.web_server as ws

BIND = "this instance is not bound to loopback"
FORCED = "demo mode is forced by OPENOSINT_DEMO_MODE"


def _client(host):
    return AsyncClient(transport=ASGITransport(app=ws.create_app(host=host, port=8080)), base_url="http://127.0.0.1:8080")


@pytest.mark.parametrize("path", ["/api/health", "/api/policy"])
async def test_forced_demo_mode_on_loopback_does_not_claim_a_non_loopback_bind(monkeypatch, path):
    monkeypatch.setenv("OPENOSINT_DEMO_MODE", "true")
    async with _client("127.0.0.1") as c:
        body = (await c.get(path)).json()
    assert body["restricted"] is True
    assert body["restriction_reason"] == FORCED


@pytest.mark.parametrize("path", ["/api/health", "/api/policy"])
async def test_exposed_bind_still_reports_the_bind(monkeypatch, path):
    monkeypatch.delenv("OPENOSINT_DEMO_MODE", raising=False)
    monkeypatch.delenv("OPENOSINT_PUBLISHED_BIND", raising=False)
    async with _client("0.0.0.0") as c:
        body = (await c.get(path)).json()
    assert body["restriction_reason"] == BIND


async def test_bind_reason_wins_when_both_apply(monkeypatch):
    monkeypatch.setenv("OPENOSINT_DEMO_MODE", "true")
    monkeypatch.delenv("OPENOSINT_PUBLISHED_BIND", raising=False)
    async with _client("0.0.0.0") as c:
        assert (await c.get("/api/policy")).json()["restriction_reason"] == BIND


async def test_unrestricted_loopback_has_no_reason(monkeypatch):
    monkeypatch.delenv("OPENOSINT_DEMO_MODE", raising=False)
    async with _client("127.0.0.1") as c:
        assert (await c.get("/api/policy")).json()["restriction_reason"] is None


def test_ui_shows_the_reason():
    html = (Path(ws.__file__).parent / "web" / "index.html").read_text(encoding="utf-8")
    assert "policy.restriction_reason" in html
