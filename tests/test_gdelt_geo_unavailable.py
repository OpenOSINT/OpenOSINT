"""When GDELT GEO fails, the tool returns one structured 'service unavailable' result."""

from __future__ import annotations

import pytest
import requests

from openosint.tools import search_gdelt_geo as geo
from openosint.tools.exceptions import OSINTError, ToolExecutionError

HEADLINE = "Scan error: GDELT GEO service unavailable, try again later."


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    monkeypatch.setattr(geo, "_cache_get", lambda _key: None)
    monkeypatch.setattr(geo, "_cache_set", lambda *_a: None)


class _Response:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


@pytest.mark.parametrize(
    "outcome",
    [
        _Response(404),
        _Response(429),
        _Response(500),
        _Response(200, bad_json=True),
        _Response(200, payload={"unexpected": True}),
        requests.ConnectTimeout("connect"),
        requests.ReadTimeout("read"),
        requests.ConnectionError("dns"),
    ],
    ids=lambda o: type(o).__name__ + str(getattr(o, "status_code", "")),
)
async def test_every_upstream_failure_gives_the_structured_result(monkeypatch, outcome):
    def fake_get(*_a, **_k):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(geo.requests, "get", fake_get)

    result = await geo.run_gdelt_geo_osint("ukraine")

    lines = result.splitlines()
    assert lines[0] == HEADLINE
    assert lines[1] == geo.SERVICE_UNAVAILABLE_MARKER
    assert lines[2].startswith("Reason: ")
    assert "Traceback" not in result and "Exception" not in result


async def test_http_404_reason_names_the_status(monkeypatch):
    monkeypatch.setattr(geo.requests, "get", lambda *_a, **_k: _Response(404))

    assert "HTTP 404" in await geo.run_gdelt_geo_osint("ukraine")


@pytest.mark.parametrize("error", [OSINTError("boom"), ToolExecutionError("boom")])
async def test_tool_errors_are_covered(monkeypatch, error):
    def boom(*_a):
        raise error

    monkeypatch.setattr(geo, "fetch_gdelt_data", boom)

    assert (await geo.run_gdelt_geo_osint("x")).startswith(HEADLINE)


async def test_success_is_unchanged_and_not_flagged(monkeypatch):
    fc = {"type": "FeatureCollection", "features": []}
    monkeypatch.setattr(geo, "fetch_gdelt_data", lambda *_a: fc)

    result = await geo.run_gdelt_geo_osint("ukraine")

    assert geo.SERVICE_UNAVAILABLE_MARKER not in result
    assert result.startswith("No geolocated coverage found")


async def test_other_tools_still_see_the_scan_error_prefix_the_ui_colours_red():
    assert HEADLINE.startswith("Scan error:")
