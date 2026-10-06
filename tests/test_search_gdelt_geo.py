"""search_gdelt_geo over the GKG window: query, bbox, coverage, failures. No live network."""

from __future__ import annotations

import json
import re
import threading

import pytest
import requests

from openosint import proxy
from openosint.tools import gdelt_gkg as gkg
from openosint.tools import search_gdelt_geo as geo
from tests.test_gdelt_gkg import FakeUpstream, make_zip, row, slot_now, wait_for_backfill

HEADLINE = "Scan error: GDELT GEO service unavailable, try again later."
KYIV = "4#Kyiv, Ukraine#UP#UP12##50.45#30.52#-1#10"
NYC = "3#New York, United States#US#USNY##40.71#-74.0#-2#10"
FIJI = "4#Suva, Fiji#FJ#FJ01##-18.14#178.44#-3#10"  # east of the antimeridian

KYIV_ROW = row(
    url="https://news.example/ukraine-talks", title="Talks in Kyiv about the war", places=KYIV
)
NYC_ROW = row(url="https://news.example/nyc", title="New York transit strike", places=NYC)
FIJI_ROW = row(url="https://news.example/fiji", title="Fiji cyclone warning", places=FIJI)


@pytest.fixture(autouse=True)
def _fresh_window(monkeypatch):
    monkeypatch.setattr(gkg, "_BACKFILL_PAUSE_SECONDS", 0)
    monkeypatch.setenv(gkg.WINDOW_HOURS_ENV, "1")
    gkg.get_window().clear()
    yield
    wait_for_backfill(gkg.get_window())
    gkg.get_window().clear()


def serve(monkeypatch, *rows: str, full: bool = False) -> FakeUpstream:
    """Serve rows for the newest slot; older slots 404 unless full=True (keeps counts exact)."""
    upstream = FakeUpstream(slot_now(), only_newest=not full)
    upstream.zip_bytes = make_zip("\n".join(rows).encode())
    monkeypatch.setattr(gkg, "_download", upstream)
    return upstream


def fence(result: str) -> dict:
    return json.loads(re.search(r"```geojson\n(.*?)```", result, re.DOTALL).group(1))


def names(result: str) -> list[str]:
    if "```geojson" not in result:
        return []
    return sorted(f["properties"]["name"] for f in fence(result)["features"])


# --- happy path ------------------------------------------------------------


async def test_matching_articles_become_point_features_with_fence(monkeypatch):
    serve(monkeypatch, KYIV_ROW, NYC_ROW)

    result = await geo.run_gdelt_geo_osint("kyiv")

    feature = fence(result)["features"][0]
    assert names(result) == ["Kyiv, Ukraine"]
    assert feature["geometry"] == {"type": "Point", "coordinates": [30.52, 50.45]}
    assert feature["properties"]["title"] == "Talks in Kyiv about the war"
    assert feature["properties"]["url"] == "https://news.example/ukraine-talks"
    assert feature["properties"]["count"] == 1
    assert "[+] Kyiv, Ukraine (50.45, 30.52)" in result


async def test_model_bound_text_carries_no_headlines_or_urls(monkeypatch):
    serve(monkeypatch, KYIV_ROW)

    text, raw = geo.split_geojson_fence(await geo.run_gdelt_geo_osint("kyiv"))

    assert raw is not None
    assert "Talks in Kyiv" not in text and "news.example" not in text
    assert "[1 geo point(s) → globe]" in text


async def test_counts_aggregate_articles_per_place_and_sort_busiest_first(monkeypatch):
    second = row(url="https://news.example/2", title="Second Kyiv story", places=KYIV)
    third = row(url="https://news.example/3", title="Kyiv again", places=KYIV)
    serve(monkeypatch, KYIV_ROW, second, third, NYC_ROW)

    fc = fence(await geo.run_gdelt_geo_osint("*"))

    assert [(f["properties"]["name"], f["properties"]["count"]) for f in fc["features"]] == [
        ("Kyiv, Ukraine", 3),
        ("New York, United States", 1),
    ]


@pytest.mark.parametrize(
    "query,expected",
    [
        ('"new york"', ["New York, United States"]),
        ("fiji OR kyiv", ["Kyiv, Ukraine", "Suva, Fiji"]),
        ("kyiv war", ["Kyiv, Ukraine"]),
        ("kyiv strike", []),
        ("KYIV", ["Kyiv, Ukraine"]),
        ("*", ["Kyiv, Ukraine", "New York, United States", "Suva, Fiji"]),
        ("", ["Kyiv, Ukraine", "New York, United States", "Suva, Fiji"]),
    ],
)
async def test_query_syntax(monkeypatch, query, expected):
    serve(monkeypatch, KYIV_ROW, NYC_ROW, FIJI_ROW)

    assert names(await geo.run_gdelt_geo_osint(query)) == sorted(expected)


async def test_empty_result_says_so_without_a_fence(monkeypatch):
    serve(monkeypatch, KYIV_ROW)

    result = await geo.run_gdelt_geo_osint("nothing matches this")

    assert result.startswith("No geolocated coverage found")
    assert "```geojson" not in result


# --- bbox ------------------------------------------------------------------


async def test_bbox_keeps_only_places_inside(monkeypatch):
    serve(monkeypatch, KYIV_ROW, NYC_ROW)

    result = await geo.run_gdelt_geo_osint("*", bbox=(20.0, 40.0, 40.0, 60.0))

    assert names(result) == ["Kyiv, Ukraine"]


async def test_bbox_crossing_the_antimeridian(monkeypatch):
    serve(monkeypatch, FIJI_ROW, KYIV_ROW)

    result = await geo.run_gdelt_geo_osint("*", bbox=(170.0, -30.0, -170.0, 0.0))

    assert names(result) == ["Suva, Fiji"]


@pytest.mark.parametrize(
    "bad", [[1, 2, 3], "abc", [0, 0, "x", 1], [0, 50, 10, 40], [0, -100, 10, 0], [200, 0, 210, 1]]
)
async def test_malformed_bbox_is_rejected_cleanly(monkeypatch, bad):
    upstream = serve(monkeypatch, KYIV_ROW)

    result = await geo.run_gdelt_geo_osint("*", bbox=bad)

    assert result.startswith("Invalid input: ")
    assert upstream.calls == []  # rejected before touching the network


# --- clamps and coverage ---------------------------------------------------


async def test_maxpoints_is_clamped_and_applied(monkeypatch):
    rows = [
        row(url=f"https://n.example/{i}", places=f"4#P{i}#XX#XX##{i}.5#{i}.5#-{i}#1")
        for i in range(1, 6)
    ]
    serve(monkeypatch, *rows)

    assert len(fence(await geo.run_gdelt_geo_osint("*", maxpoints=2))["features"]) == 2
    assert len(fence(await geo.run_gdelt_geo_osint("*", maxpoints=-5))["features"]) == 1


async def test_first_query_reports_a_short_window_so_it_is_not_mistaken_for_missing_data(
    monkeypatch,
):
    upstream = serve(monkeypatch, KYIV_ROW, full=True)
    upstream.gate = threading.Event()  # hold the backfill so the first answer is the short one

    result = await geo.run_gdelt_geo_osint("kyiv", timespan=60)
    upstream.gate.set()

    assert fence(result)["coverage"] == {
        "minutes": 15,
        "requested": 60,
        "loading": True,
        "stale_minutes": 0,
    }
    assert (
        "Coverage: the last 15 min (of the 1 h requested; older articles are still loading"
        in result
    )


async def test_full_window_reports_full_coverage(monkeypatch):
    serve(monkeypatch, KYIV_ROW, full=True)
    await geo.run_gdelt_geo_osint("kyiv")
    wait_for_backfill(gkg.get_window())

    result = await geo.run_gdelt_geo_osint("kyiv", timespan=60)

    assert fence(result)["coverage"] == {
        "minutes": 60,
        "requested": 60,
        "loading": False,
        "stale_minutes": 0,
    }
    assert "Coverage: the last 1 h." in result


async def test_timespan_beyond_the_window_is_reported_as_the_window(monkeypatch):
    serve(monkeypatch, KYIV_ROW, full=True)
    await geo.run_gdelt_geo_osint("kyiv")
    wait_for_backfill(gkg.get_window())

    coverage = fence(await geo.run_gdelt_geo_osint("kyiv", timespan=99999))["coverage"]

    assert coverage["requested"] == 60 and coverage["minutes"] == 60


# --- failures --------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        gkg.GkgError("GDELT file server returned HTTP 404."),
        gkg.GkgError("GDELT file is larger than the allowed size."),
        gkg.GkgError("GDELT file is not a valid zip: bad"),
    ],
)
async def test_every_failure_gives_the_structured_result(monkeypatch, error):
    def down(*_a):
        raise error

    monkeypatch.setattr(gkg, "_download", down)

    lines = (await geo.run_gdelt_geo_osint("ukraine")).splitlines()

    assert lines[0] == HEADLINE
    assert lines[1] == geo.SERVICE_UNAVAILABLE_MARKER
    assert lines[2] == f"Reason: {error}"
    assert "Traceback" not in "\n".join(lines)


@pytest.mark.parametrize(
    "exc", [requests.ConnectTimeout("c"), requests.ReadTimeout("r"), requests.ConnectionError("d")]
)
async def test_network_errors_end_in_the_structured_result(monkeypatch, exc):
    def fake_get(*_a, **_k):
        raise exc

    monkeypatch.setattr(gkg.requests, "get", fake_get)

    assert geo.SERVICE_UNAVAILABLE_MARKER in await geo.run_gdelt_geo_osint("ukraine")


async def test_oversized_upstream_body_fails_closed(monkeypatch):
    class Huge:
        status_code = 200
        headers = {"Content-Length": str(gkg.MAX_COMPRESSED_BYTES + 1)}

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(gkg.requests, "get", lambda *_a, **_k: Huge())

    assert geo.SERVICE_UNAVAILABLE_MARKER in await geo.run_gdelt_geo_osint("x")


async def test_unexpected_bug_is_not_reported_as_unavailable(monkeypatch):
    def boom(*_a):
        raise ZeroDivisionError

    monkeypatch.setattr(geo, "build_feature_collection", boom)
    serve(monkeypatch, KYIV_ROW)

    result = await geo.run_gdelt_geo_osint("x")

    assert result.startswith("Internal error") and geo.SERVICE_UNAVAILABLE_MARKER not in result


async def test_success_is_not_flagged_unavailable(monkeypatch):
    serve(monkeypatch, KYIV_ROW)

    assert geo.SERVICE_UNAVAILABLE_MARKER not in await geo.run_gdelt_geo_osint("kyiv")


# --- hostile third-party content ------------------------------------------


async def test_hostile_titles_and_urls_never_reach_the_globe_executable(monkeypatch):
    serve(
        monkeypatch,
        row(url="javascript:alert(1)", title="js link", places=KYIV),
        row(url="data:text/html,<script>1</script>", title="data link", places=KYIV),
        row(url="https://ok.example/x", title="<script>alert(1)</script>", places=NYC),
    )

    result = await geo.run_gdelt_geo_osint("*")
    fc = fence(result)

    assert [f["properties"]["url"] for f in fc["features"]] == ["https://ok.example/x"]
    assert not re.search(r"javascript:|data:text", result, re.IGNORECASE)
    # The script-tag title survives only as literal text inside JSON the UI renders via x-text.
    assert fc["features"][0]["properties"]["title"] == "<script>alert(1)</script>"
    assert "<script>" not in geo.split_geojson_fence(result)[0]


# --- proxy: GDELT is public, so the shared proxy is bypassed by default ----


class _Streamed:
    status_code = 200
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def iter_content(self, _size):
        yield b"junk"


@pytest.fixture
def _proxy_clean(monkeypatch):
    proxy.set_cli_proxy_url(None)
    monkeypatch.delenv(proxy._ENV_VAR, raising=False)
    yield
    proxy.set_cli_proxy_url(None)


def _capture_requests(monkeypatch) -> dict:
    seen: dict = {}

    def fake_get(_url, **kwargs):
        seen.update(kwargs)
        return _Streamed()

    monkeypatch.setattr(gkg.requests, "get", fake_get)
    return seen


async def test_no_proxy_even_when_configured(monkeypatch, _proxy_clean):
    monkeypatch.setenv(proxy._ENV_VAR, "http://proxyhost:8080")
    seen = _capture_requests(monkeypatch)

    await geo.run_gdelt_geo_osint("proxy-bypass")

    assert seen["proxies"] is None


async def test_opt_in_env_var_restores_proxy(monkeypatch, _proxy_clean):
    monkeypatch.setenv(proxy._ENV_VAR, "http://proxyhost:8080")
    monkeypatch.setenv("OPENOSINT_GDELT_USE_PROXY", "1")
    seen = _capture_requests(monkeypatch)

    await geo.run_gdelt_geo_osint("proxy-optin")

    assert seen["proxies"] == {"http": "http://proxyhost:8080", "https": "http://proxyhost:8080"}


def test_fence_helper_passes_other_tools_through_unchanged():
    assert geo.split_geojson_fence("[+] something") == ("[+] something", None)
