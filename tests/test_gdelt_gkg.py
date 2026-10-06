"""GKG window: parsing, download safety, lazy loading, backfill, caps. No live network."""

from __future__ import annotations

import io
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from openosint.tools import gdelt_gkg as gkg

FIXTURES = Path(__file__).parent / "fixtures" / "gdelt"
SAMPLE_TSV = (FIXTURES / "gkg_sample.tsv").read_bytes()
LASTUPDATE = (FIXTURES / "lastupdate.txt").read_text()
KYIV = "4#Kyiv, Ukraine#UP#UP12##50.45#30.52#-1#10"


def make_zip(payload: bytes = SAMPLE_TSV, name: str = "x.gkg.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, payload)
    return buf.getvalue()


def row(url="https://example.com/a", title="A title", places=KYIV, domain="example.com"):
    cols = [""] * 27
    cols[3], cols[4], cols[10], cols[15] = domain, url, places, "-2.5,1,1"
    cols[26] = f"<PAGE_TITLE>{title}</PAGE_TITLE>"
    return "\t".join(cols)


def slot_now() -> str:
    moment = datetime.now(timezone.utc)
    moment = moment.replace(minute=moment.minute // 15 * 15, second=0, microsecond=0)
    return moment.strftime("%Y%m%d%H%M%S")


def slot_minus(slot: str, minutes: int) -> str:
    moment = datetime.strptime(slot, "%Y%m%d%H%M%S") - timedelta(minutes=minutes)
    return moment.strftime("%Y%m%d%H%M%S")


@pytest.fixture(autouse=True)
def _fresh_window(monkeypatch):
    monkeypatch.setattr(gkg, "_BACKFILL_PAUSE_SECONDS", 0)
    monkeypatch.delenv(gkg.WINDOW_HOURS_ENV, raising=False)
    monkeypatch.delenv(gkg.MAX_ARTICLES_ENV, raising=False)
    gkg.get_window().clear()
    yield
    gkg.get_window().clear()


class FakeUpstream:
    """Stands in for gkg._download; records every URL requested."""

    def __init__(
        self, newest_slot: str, missing: set[str] | None = None, only_newest: bool = False
    ):
        self.newest_slot = newest_slot
        self.only_newest = only_newest  # every older slot 404s
        self.gate: threading.Event | None = None  # when set, older slots wait for it
        self.zip_bytes = make_zip()
        self.missing = missing or set()
        self.calls: list[str] = []
        self.lock = threading.Lock()

    def __call__(self, url, max_bytes, timeout_seconds):
        with self.lock:
            self.calls.append(url)
        if url == gkg.LASTUPDATE_URL:
            return f"1 a http://data.gdeltproject.org/gdeltv2/{self.newest_slot}.gkg.csv.zip\n".encode()
        if self.gate is not None and self.newest_slot not in url:
            self.gate.wait(10)
        if any(slot in url for slot in self.missing) or (
            self.only_newest and self.newest_slot not in url
        ):
            raise gkg.GkgError("GDELT file server returned HTTP 404.")
        return self.zip_bytes

    def downloads(self) -> list[str]:
        return [c for c in self.calls if c != gkg.LASTUPDATE_URL]


def wait_for_backfill(window: gkg.GkgWindow, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while window._backfilling and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not window._backfilling


# --- parsing ---------------------------------------------------------------


def test_parses_recorded_fixture_into_articles_with_places():
    articles = gkg.parse_gkg_zip(make_zip(), "20261006181500")

    assert len(articles) >= 30
    for article in articles:
        assert article.title and article.url.startswith(("http://", "https://"))
        assert article.places
        assert all(-90 <= p.lat <= 90 and -180 <= p.lon <= 180 for p in article.places)


def test_country_centroids_are_dropped_and_rows_without_places_skipped():
    country_only = row(places="1#Russia#RS#RS##60#100#RS#10")
    articles = gkg.parse_gkg_zip(make_zip("\n".join([country_only, row()]).encode()), "s")

    assert len(articles) == 1
    assert articles[0].places[0].name == "Kyiv, Ukraine"


def test_places_ordered_by_first_mention_and_capped():
    places = ";".join(f"4#P{i}#XX#XX##{i}.5#{i}.5#-{i}#{100 - i}" for i in range(1, 9))
    article = gkg.parse_gkg_zip(make_zip(row(places=places).encode()), "s")[0]

    assert len(article.places) == gkg.MAX_PLACES_PER_ARTICLE
    assert article.places[0].name == "P8"  # smallest char offset


def test_title_entities_are_decoded_to_plain_text_and_capped():
    title = "Poor suffer &#x2014; IMF " + "x" * 500
    article = gkg.parse_gkg_zip(make_zip(row(title=title).encode()), "s")[0]

    assert article.title.startswith("Poor suffer — IMF")
    assert len(article.title) == gkg.MAX_TITLE_CHARS


@pytest.mark.parametrize(
    "bad_url",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "//evil.example/x",
        "ftp://example.com/x",
        "https://",
        "https://exa mple.com/x",
        "https://example.com/" + "a" * 3000,
        "https://example.com/\x01x",
    ],
)
def test_hostile_urls_drop_the_article(bad_url):
    assert gkg.parse_gkg_zip(make_zip(row(url=bad_url).encode()), "s") == ()


def test_hostile_title_is_kept_only_as_inert_text_and_domain_is_validated():
    title = "<script>alert(1)</script><img src=x onerror=alert(1)>"
    payload = row(title=title, domain="evil.com<script>").encode()
    article = gkg.parse_gkg_zip(make_zip(payload), "s")[0]

    # Literal text: the UI renders titles with x-text/textContent only.
    assert article.title == title
    assert article.domain == ""


def test_title_with_control_characters_is_cleaned():
    article = gkg.parse_gkg_zip(make_zip(row(title="a\x01b\x1bc d").encode()), "s")[0]

    assert article.title == "a b c d"


def test_malformed_rows_are_skipped_not_fatal():
    payload = b"garbage\n\t\t\n" + row().encode() + b"\n\xff\xfe\xfd\n"

    assert len(gkg.parse_gkg_zip(make_zip(payload), "s")) == 1


# --- download safety -------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://data.gdeltproject.org/gdeltv2/lastupdate.txt",
        "https://data.gdeltproject.org.evil.com/gdeltv2/x.gkg.csv.zip",
        "https://evil.com/data.gdeltproject.org/x",
        "https://user@data.gdeltproject.org/x",
        "https://data.gdeltproject.org:8443/x",
        "https://api.gdeltproject.org/x",
        "file:///etc/passwd",
        "https://data.gdeltproject.org@evil.com/x",
    ],
)
def test_only_https_data_gdeltproject_org_is_allowed(url):
    assert not gkg.is_allowed_gdelt_url(url)


def test_download_refuses_a_disallowed_url_without_touching_the_network(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("network must not be used")

    monkeypatch.setattr(gkg.requests, "get", boom)
    with pytest.raises(gkg.GkgError, match="non-GDELT"):
        gkg._download("https://evil.example/x.zip", 100, 5)


def test_lastupdate_takes_the_slot_but_ignores_foreign_hosts():
    assert gkg.parse_lastupdate(LASTUPDATE) == "20261006181500"
    hostile = (
        "1 a http://evil.com/gdeltv2/20261006181500.gkg.csv.zip\n"
        "1 a https://data.gdeltproject.org/other/20261006181500.gkg.csv.zip\n"
    )
    with pytest.raises(gkg.GkgError):
        gkg.parse_lastupdate(hostile)
    with pytest.raises(gkg.GkgError):
        gkg.parse_lastupdate("1 a https://data.gdeltproject.org/gdeltv2/99999999999999.gkg.csv.zip")


class _Response:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def iter_content(self, size):
        for i in range(0, len(self._body), size):
            yield self._body[i : i + size]

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_download_never_follows_redirects_and_checks_status(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen.update(kwargs)
        return _Response(301)

    monkeypatch.setattr(gkg.requests, "get", fake_get)
    with pytest.raises(gkg.GkgError, match="HTTP 301"):
        gkg._download(gkg.LASTUPDATE_URL, 1000, 5)
    assert seen["allow_redirects"] is False and seen["stream"] is True


def test_download_rejects_declared_and_streamed_oversize(monkeypatch):
    declared = _Response(headers={"Content-Length": "5000"})
    monkeypatch.setattr(gkg.requests, "get", lambda *_a, **_k: declared)
    with pytest.raises(gkg.GkgError, match="larger"):
        gkg._download(gkg.LASTUPDATE_URL, 1000, 5)

    undeclared = _Response(body=b"x" * 5000)  # no Content-Length: must still be capped
    monkeypatch.setattr(gkg.requests, "get", lambda *_a, **_k: undeclared)
    with pytest.raises(gkg.GkgError, match="larger"):
        gkg._download(gkg.LASTUPDATE_URL, 1000, 5)


@pytest.mark.parametrize(
    "exc", [requests.ConnectTimeout("c"), requests.ReadTimeout("r"), requests.ConnectionError("d")]
)
def test_download_maps_network_errors_to_gkg_error(monkeypatch, exc):
    def fake_get(*_a, **_k):
        raise exc

    monkeypatch.setattr(gkg.requests, "get", fake_get)
    with pytest.raises(gkg.GkgError):
        gkg._download(gkg.LASTUPDATE_URL, 1000, 5)


def test_zip_bomb_is_stopped_by_the_decompressed_cap(monkeypatch):
    monkeypatch.setattr(gkg, "MAX_DECOMPRESSED_BYTES", 100_000)
    bomb = make_zip(b"A" * 5_000_000)
    assert len(bomb) < 20_000  # small on the wire, big once expanded

    with pytest.raises(gkg.GkgError, match="expands"):
        gkg.parse_gkg_zip(bomb, "s")


def test_overlong_lines_are_dropped_and_parsing_continues(monkeypatch):
    monkeypatch.setattr(gkg, "MAX_LINE_BYTES", 10_000)
    payload = b"x" * 200_000 + b"\n" + row().encode() + b"\n"

    assert len(gkg.parse_gkg_zip(make_zip(payload), "s")) == 1


@pytest.mark.parametrize("blob", [b"not a zip", b"", make_zip()[:50]])
def test_corrupt_archives_fail_closed(blob):
    with pytest.raises(gkg.GkgError):
        gkg.parse_gkg_zip(blob, "s")


def test_multi_member_archive_is_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("a", SAMPLE_TSV)
        archive.writestr("b", SAMPLE_TSV)

    with pytest.raises(gkg.GkgError, match="layout"):
        gkg.parse_gkg_zip(buf.getvalue(), "s")


# --- window behaviour ------------------------------------------------------


def test_nothing_is_downloaded_until_a_query_asks(monkeypatch):
    upstream = FakeUpstream(slot_now())
    monkeypatch.setattr(gkg, "_download", upstream)

    gkg.get_window()  # merely obtaining the window is free
    gkg.GkgWindow()

    assert upstream.calls == []


def test_first_snapshot_loads_only_the_newest_file_then_backfills_in_background(monkeypatch):
    upstream = FakeUpstream(slot_now())
    monkeypatch.setattr(gkg, "_download", upstream)
    window = gkg.GkgWindow()

    first = window.snapshot()

    assert first.articles and first.covered_minutes == gkg.SLOT_MINUTES
    assert first.window_minutes == 360
    assert first.loading is True

    wait_for_backfill(window)
    full = window.snapshot()
    assert full.covered_minutes == 360 and full.loading is False
    downloads = upstream.downloads()
    assert len(downloads) == len(set(downloads)) == 24  # each slot exactly once


def test_concurrent_queries_never_download_the_same_slot_twice(monkeypatch):
    upstream = FakeUpstream(slot_now())
    monkeypatch.setattr(gkg, "_download", upstream)
    window = gkg.GkgWindow()

    threads = [threading.Thread(target=window.snapshot) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    wait_for_backfill(window)

    downloads = upstream.downloads()
    assert len(downloads) == len(set(downloads)) == 24


def test_lastupdate_is_polled_at_most_once_per_interval(monkeypatch):
    upstream = FakeUpstream(slot_now())
    monkeypatch.setattr(gkg, "_download", upstream)
    window = gkg.GkgWindow()
    window.snapshot()
    wait_for_backfill(window)

    for _ in range(20):
        window.snapshot()

    assert upstream.calls.count(gkg.LASTUPDATE_URL) == 1


def test_window_hours_env_controls_the_window(monkeypatch):
    monkeypatch.setenv(gkg.WINDOW_HOURS_ENV, "1")
    upstream = FakeUpstream(slot_now())
    monkeypatch.setattr(gkg, "_download", upstream)
    window = gkg.GkgWindow()

    window.snapshot()
    wait_for_backfill(window)

    assert window.snapshot().covered_minutes == 60
    assert len(upstream.downloads()) == 4


@pytest.mark.parametrize("raw,expected", [("", 6), ("3", 3), ("0", 1), ("999", 24), ("abc", 6)])
def test_window_hours_is_clamped_and_tolerates_junk(monkeypatch, raw, expected):
    monkeypatch.setenv(gkg.WINDOW_HOURS_ENV, raw)

    assert gkg.window_hours() == expected


def test_a_skipped_upstream_slot_does_not_stop_the_backfill(monkeypatch):
    newest = slot_now()
    upstream = FakeUpstream(newest, missing={slot_minus(newest, 30)})
    monkeypatch.setattr(gkg, "_download", upstream)
    window = gkg.GkgWindow()

    window.snapshot()
    wait_for_backfill(window)

    assert window.snapshot().covered_minutes == 360  # oldest slot still reached


def test_backfill_gives_up_after_consecutive_failures_and_backs_off(monkeypatch):
    newest = slot_now()
    upstream = FakeUpstream(newest)

    def flaky(url, max_bytes, timeout_seconds):
        if url == gkg.LASTUPDATE_URL or newest in url:
            return upstream(url, max_bytes, timeout_seconds)
        raise gkg.GkgError("HTTP 503")

    monkeypatch.setattr(gkg, "_download", flaky)
    window = gkg.GkgWindow()
    window.snapshot()
    wait_for_backfill(window)

    snapshot = window.snapshot()

    assert snapshot.covered_minutes == gkg.SLOT_MINUTES and snapshot.loading is False
    assert window._backfill_retry_after > time.monotonic()  # no hammering on every query


def test_cold_failure_raises_and_backs_off_instead_of_retrying_every_query(monkeypatch):
    calls = []

    def down(url, *_a):
        calls.append(url)
        raise gkg.GkgError("HTTP 404")

    monkeypatch.setattr(gkg, "_download", down)
    window = gkg.GkgWindow()

    with pytest.raises(gkg.GkgError):
        window.snapshot()
    with pytest.raises(gkg.GkgError):
        window.snapshot()

    assert len(calls) == 1  # the second query was answered from the backoff


def test_recent_data_is_served_when_a_refresh_fails_but_old_data_is_not(monkeypatch):
    monkeypatch.setattr(gkg, "_download", FakeUpstream(slot_now()))
    monkeypatch.setattr(gkg, "_POLL_INTERVAL_SECONDS", 0)
    window = gkg.GkgWindow()
    window.snapshot()
    wait_for_backfill(window)

    def down(*_a):
        raise gkg.GkgError("HTTP 500")

    monkeypatch.setattr(gkg, "_download", down)
    assert window.snapshot().articles  # recent data still answers

    monkeypatch.setattr(gkg, "STALE_LIMIT_MINUTES", -1)
    window._retry_after = 0
    with pytest.raises(gkg.GkgError):
        window.snapshot()


def test_article_cap_drops_oldest_first(monkeypatch):
    monkeypatch.setattr(gkg, "max_articles", lambda: 40)
    newest = slot_now()
    monkeypatch.setattr(gkg, "_download", FakeUpstream(newest))
    window = gkg.GkgWindow()

    window.snapshot()
    wait_for_backfill(window)
    snapshot = window.snapshot()

    assert len(snapshot.articles) <= 40
    assert snapshot.articles[-1].slot == newest  # newest survives
    assert snapshot.covered_minutes < 360  # the oldest slots were the ones dropped


def test_old_slots_fall_out_of_the_window(monkeypatch):
    monkeypatch.setenv(gkg.WINDOW_HOURS_ENV, "1")
    old = slot_minus(slot_now(), 300)
    monkeypatch.setattr(gkg, "_download", FakeUpstream(slot_now()))
    window = gkg.GkgWindow()
    window._files = {old: gkg.parse_gkg_zip(make_zip(), old)}

    window.snapshot()
    wait_for_backfill(window)

    assert old not in window._files
