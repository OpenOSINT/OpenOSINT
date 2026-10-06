"""POST /api/run/search_gdelt_geo must pass the selected bbox through to the tool."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def http_client():
    import openosint.web_server as ws

    ws._RATE_STORE.clear()
    app = ws.create_app(host="127.0.0.1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as client:
        yield client
    ws._RATE_STORE.clear()


async def test_bbox_in_the_request_reaches_the_tool(http_client):
    received: list = []

    async def fake_geo(query, timeout_seconds=15, *, timespan=60, maxpoints=250, bbox=None):
        received.append((query, bbox))
        return "ok"

    with patch("openosint.web_server.run_gdelt_geo_osint", new=fake_geo):
        resp = await http_client.post(
            "/api/run/search_gdelt_geo",
            json={"input": "*", "bbox": [20, 40, 40, 60]},
        )

    assert resp.status_code == 200
    assert received == [("*", (20, 40, 40, 60))]


async def test_no_bbox_means_none(http_client):
    received: list = []

    async def fake_geo(query, timeout_seconds=15, *, timespan=60, maxpoints=250, bbox=None):
        received.append(bbox)
        return "ok"

    with patch("openosint.web_server.run_gdelt_geo_osint", new=fake_geo):
        await http_client.post("/api/run/search_gdelt_geo", json={"input": "ukraine"})

    assert received == [None]


@pytest.mark.parametrize("bad", [[1, 2, 3], [1, 2, 3, 4, 5], "abc", ["a", "b", "c", "d"]])
async def test_malformed_bbox_is_a_422_and_never_runs_the_tool(http_client, bad):
    called: list = []

    async def fake_geo(*_a, **_k):
        called.append(1)
        return "ok"

    with patch("openosint.web_server.run_gdelt_geo_osint", new=fake_geo):
        resp = await http_client.post("/api/run/search_gdelt_geo", json={"input": "*", "bbox": bad})

    assert resp.status_code == 422
    assert called == []


async def test_other_tools_ignore_a_bbox(http_client):
    received: list = []

    async def fake_whois(value, timeout_seconds=15):
        received.append(value)
        return "ok"

    with patch("openosint.web_server.run_whois_osint", new=fake_whois):
        resp = await http_client.post(
            "/api/run/search_whois", json={"input": "example.com", "bbox": [1, 2, 3, 4]}
        )

    assert resp.status_code == 200 and received == ["example.com"]
