# openosint/tools/gdelt_gkg.py
"""
Rolling in-memory window of GDELT 2.0 GKG (Global Knowledge Graph) articles.

GDELT publishes one GKG file every 15 minutes at data.gdeltproject.org (a
public Google Cloud Storage bucket; keyless, no account). Each row is a news
article with its headline, URL and the places it mentions (lat/lon). This
module keeps the most recent window of those articles in memory so
search_gdelt_geo can answer from RAM — upstream load is one small poll plus
one file per 15 minutes however many queries arrive.

Design rules:
  * Lazy only. Nothing is downloaded until a query calls snapshot(); a local
    install that never uses the tool never touches the network.
  * The first query loads only the newest file; older files backfill on one
    background thread, one download at a time (single-flight).
  * Everything downloaded is untrusted: https + data.gdeltproject.org only,
    no redirects, compressed and decompressed size caps, per-field length
    caps, article/URL validation. Any violation raises GkgError, which the
    tool turns into its structured "service unavailable" result.
  * Memory is capped: at most max_articles() stored, oldest dropped first.
"""

from __future__ import annotations

import html
import io
import logging
import os
import re
import threading
import time
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import NamedTuple
from urllib.parse import urlsplit

import requests

from openosint.proxy import get_requests_proxies

logger = logging.getLogger(__name__)

ALLOWED_HOST = "data.gdeltproject.org"
LASTUPDATE_URL = f"https://{ALLOWED_HOST}/gdeltv2/lastupdate.txt"
_GKG_URL_TEMPLATE = f"https://{ALLOWED_HOST}/gdeltv2/{{ts}}.gkg.csv.zip"
_GKG_PATH_RE = re.compile(r"^/gdeltv2/(\d{14})\.gkg\.csv\.zip$")

SLOT_MINUTES = 15
WINDOW_HOURS_ENV = "OPENOSINT_GDELT_WINDOW_HOURS"
MAX_ARTICLES_ENV = "OPENOSINT_GDELT_MAX_ARTICLES"
DEFAULT_WINDOW_HOURS = 6
MAX_WINDOW_HOURS = 24
DEFAULT_MAX_ARTICLES = 30_000

# Download safety. Real files: ~7.7 MB compressed, ~26 MB decompressed.
MAX_LASTUPDATE_BYTES = 8 * 1024
MAX_COMPRESSED_BYTES = 24 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 96 * 1024 * 1024
MAX_LINE_BYTES = 4 * 1024 * 1024
_CONNECT_TIMEOUT_SECONDS = 5
_READ_TIMEOUT_SECONDS = 30
_CHUNK_BYTES = 64 * 1024

# Field caps applied while parsing (everything here is third-party text).
MAX_TITLE_CHARS = 200
MAX_URL_CHARS = 2048
MAX_DOMAIN_CHARS = 253
MAX_PLACE_NAME_CHARS = 100
MAX_PLACES_PER_ARTICLE = 5

# GKG location types: 1 country, 2 US state, 3 US city, 4 world city, 5 world
# state. Type 1 is a country centroid — a dot in the middle of a country is
# not where anything happened, so it is dropped.
_KEPT_LOCATION_TYPES = frozenset({2, 3, 4, 5})

# Polite polling.
_POLL_INTERVAL_SECONDS = 300  # lastupdate.txt changes every 15 min
_FAILURE_BACKOFF_SECONDS = 60
_BACKFILL_PAUSE_SECONDS = 0.5
_BACKFILL_MAX_FAILURES = 3
STALE_LIMIT_MINUTES = 120  # keep serving old data this long if refreshes fail

_GKG_MIN_COLUMNS = 27
_COL_DOMAIN, _COL_URL, _COL_LOCATIONS, _COL_TONE, _COL_EXTRAS = 3, 4, 10, 15, 26
_TITLE_RE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.DOTALL)
_DOMAIN_RE = re.compile(r"^[A-Za-z0-9.-]+$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f  ]+")


_NEVER = float("-inf")


class GkgError(Exception):
    """Any download, size-cap or format failure; the tool reports it as unavailable."""


class Place(NamedTuple):
    name: str
    lat: float
    lon: float


class Article(NamedTuple):
    slot: str  # 14-digit GDELT slot timestamp the article arrived in
    title: str  # plain text — never HTML
    url: str  # validated http(s)
    domain: str
    tone: float
    places: tuple[Place, ...]


@dataclass(frozen=True)
class Window:
    """Immutable snapshot handed to the query layer."""

    articles: tuple[Article, ...]
    covered_minutes: int  # how far back the loaded files reach
    window_minutes: int  # how far back they will reach once loaded
    loading: bool  # backfill still running
    stale_minutes: int  # 0 unless serving old data after a failed refresh


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        logger.warning("Ignoring non-integer %s=%r", name, raw)
        value = default
    return max(lo, min(hi, value))


def window_hours() -> int:
    return _env_int(WINDOW_HOURS_ENV, DEFAULT_WINDOW_HOURS, 1, MAX_WINDOW_HOURS)


def max_articles() -> int:
    return _env_int(MAX_ARTICLES_ENV, DEFAULT_MAX_ARTICLES, 1_000, 200_000)


def _gdelt_proxies() -> dict[str, str] | None:
    # GDELT is public and not per-IP rate limited: the shared upstream proxy
    # is a pure failure point here. Opt back in with OPENOSINT_GDELT_USE_PROXY=1.
    if os.environ.get("OPENOSINT_GDELT_USE_PROXY", "").strip().lower() in ("1", "true", "yes"):
        return get_requests_proxies()
    return None


# --------------------------------------------------------------------------
# URL + download safety
# --------------------------------------------------------------------------


def is_allowed_gdelt_url(url: str) -> bool:
    """https only, exactly data.gdeltproject.org, default port, no credentials."""
    try:
        parts = urlsplit(url)
        return (
            parts.scheme == "https"
            and parts.hostname == ALLOWED_HOST
            and parts.port in (None, 443)
            and parts.username is None
            and parts.password is None
        )
    except ValueError:
        return False


def safe_article_url(raw: str) -> str:
    """Return raw if it is a plain absolute http(s) URL, else ''. Python twin of url-safety.js."""
    if not raw or len(raw) > MAX_URL_CHARS or _CONTROL_RE.search(raw) or " " in raw:
        return ""
    try:
        parts = urlsplit(raw)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return ""
    except ValueError:
        return ""
    return raw


def _download(url: str, max_bytes: int, timeout_seconds: int) -> bytes:
    """GET url (allow-listed, no redirects), refusing bodies over max_bytes."""
    if not is_allowed_gdelt_url(url):
        raise GkgError(f"Refusing to fetch non-GDELT URL: {url[:80]!r}")
    try:
        with requests.get(
            url,
            stream=True,
            allow_redirects=False,
            timeout=(_CONNECT_TIMEOUT_SECONDS, timeout_seconds),
            proxies=_gdelt_proxies(),
        ) as response:
            if response.status_code != 200:
                raise GkgError(f"GDELT file server returned HTTP {response.status_code}.")
            declared = response.headers.get("Content-Length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise GkgError("GDELT file is larger than the allowed size.")
            body = bytearray()
            for chunk in response.iter_content(_CHUNK_BYTES):
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise GkgError("GDELT file is larger than the allowed size.")
            return bytes(body)
    except requests.ConnectTimeout as exc:
        raise GkgError(
            f"GDELT file server did not respond within {_CONNECT_TIMEOUT_SECONDS}s."
        ) from exc
    except requests.Timeout as exc:
        raise GkgError(f"GDELT file server timed out after {timeout_seconds}s.") from exc
    except requests.RequestException as exc:
        raise GkgError(f"Network error reaching GDELT file server: {exc}") from exc


def parse_lastupdate(text: str) -> str:
    """Return the newest GKG slot (14 digits) listed in lastupdate.txt, or raise GkgError.

    GDELT lists plain http:// URLs there. Only the slot is taken from a line
    (and only when the host is exactly data.gdeltproject.org); the download URL
    is always rebuilt by us as https, never followed from the file.
    """
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        try:
            listed = urlsplit(parts[2])
            host_ok = listed.scheme in ("http", "https") and listed.hostname == ALLOWED_HOST
        except ValueError:
            continue
        match = _GKG_PATH_RE.match(listed.path) if host_ok else None
        if match and _slot_time(match.group(1)):
            return match.group(1)
    raise GkgError("lastupdate.txt did not list a usable GKG file.")


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def _slot_time(slot: str) -> datetime | None:
    try:
        return datetime.strptime(slot, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _slot_str(moment: datetime) -> str:
    return moment.strftime("%Y%m%d%H%M%S")


def _age_minutes(moment: datetime) -> int:
    return int((datetime.now(timezone.utc) - moment).total_seconds() // 60)


def _clean_text(raw: str, limit: int) -> str:
    return " ".join(_CONTROL_RE.sub(" ", html.unescape(raw)).split())[:limit]


def _parse_places(field: str) -> tuple[Place, ...]:
    """V2Locations: type#name#cc#adm1#adm2#lat#lon#featureid#charoffset, ';'-separated."""
    found: list[tuple[int, Place]] = []
    seen: set[tuple[float, float]] = set()
    for item in field.split(";"):
        parts = item.split("#")
        if len(parts) < 9 or not parts[0].isdigit() or int(parts[0]) not in _KEPT_LOCATION_TYPES:
            continue
        try:
            lat, lon, offset = float(parts[5]), float(parts[6]), int(parts[8])
        except ValueError:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat, lon) in seen:
            continue
        name = _clean_text(parts[1], MAX_PLACE_NAME_CHARS)
        if not name:
            continue
        seen.add((lat, lon))
        found.append((offset, Place(name, lat, lon)))
    found.sort(key=lambda pair: pair[0])  # earliest mention first = most prominent
    return tuple(place for _, place in found[:MAX_PLACES_PER_ARTICLE])


def parse_article(columns: list[str], slot: str) -> Article | None:
    """One GKG row → Article, or None when it has no usable title/URL/place."""
    if len(columns) < _GKG_MIN_COLUMNS:
        return None
    url = safe_article_url(columns[_COL_URL])
    title_match = _TITLE_RE.search(columns[_COL_EXTRAS])
    places = _parse_places(columns[_COL_LOCATIONS])
    if not url or not title_match or not places:
        return None
    title = _clean_text(title_match.group(1), MAX_TITLE_CHARS)
    if not title:
        return None
    domain = columns[_COL_DOMAIN][:MAX_DOMAIN_CHARS]
    try:
        tone = float(columns[_COL_TONE].split(",", 1)[0])
    except ValueError:
        tone = 0.0
    return Article(slot, title, url, domain if _DOMAIN_RE.match(domain) else "", tone, places)


def _iter_lines(member, cap: int):
    """Yield decoded lines from a zip member, enforcing the decompressed-size cap."""
    total = 0
    pending = b""
    skipping = False  # inside an over-long line that is being dropped
    while True:
        chunk = member.read(_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            raise GkgError("GDELT file expands beyond the allowed size.")
        *lines, pending = (pending + chunk).split(b"\n")
        for index, line in enumerate(lines):
            if index == 0 and skipping:
                skipping = False
            elif len(line) <= MAX_LINE_BYTES:
                yield line.decode("utf-8", errors="replace")
        if len(pending) > MAX_LINE_BYTES:
            pending, skipping = b"", True
    if pending and not skipping and len(pending) <= MAX_LINE_BYTES:
        yield pending.decode("utf-8", errors="replace")


def parse_gkg_zip(data: bytes, slot: str, limit: int | None = None) -> tuple[Article, ...]:
    """Parse a GKG .zip into articles. Raises GkgError on any malformed/oversized input."""
    articles: list[Article] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            if len(names) != 1:
                raise GkgError("Unexpected GKG archive layout.")
            with archive.open(names[0]) as member:
                for line in _iter_lines(member, MAX_DECOMPRESSED_BYTES):
                    article = parse_article(line.rstrip("\r").split("\t"), slot)
                    if article:
                        articles.append(article)
    except (zipfile.BadZipFile, zlib.error, OSError, EOFError) as exc:
        raise GkgError(f"GDELT file is not a valid zip: {exc}") from exc
    return tuple(articles[-limit:] if limit else articles)


# --------------------------------------------------------------------------
# The window
# --------------------------------------------------------------------------


class GkgWindow:
    """Thread-safe rolling window; one instance per process (see get_window)."""

    def __init__(self) -> None:
        self._files: dict[str, tuple[Article, ...]] = {}
        self._state_lock = threading.Lock()  # guards _files and the fields below
        self._download_lock = threading.Lock()  # one download at a time, ever
        self._backfilling = False
        self._last_poll = _NEVER  # time.monotonic() can be tiny right after boot
        self._retry_after = 0.0
        self._backfill_retry_after = 0.0
        self._last_error = ""

    def snapshot(self, timeout_seconds: int = _READ_TIMEOUT_SECONDS) -> Window:
        """Refresh if due, then return the current window.

        Raises GkgError when nothing usable is available: a cold failure, or
        cached data older than STALE_LIMIT_MINUTES after a failed refresh.
        """
        try:
            self._refresh_newest(timeout_seconds)
        except GkgError as exc:
            logger.warning("GDELT GKG refresh failed: %s", exc)
            if not self._has_recent_data():
                raise
        self._ensure_backfill(timeout_seconds)
        return self._build_window()

    def clear(self) -> None:
        with self._state_lock:
            self._files = {}
            self._last_poll = _NEVER
            self._retry_after = self._backfill_retry_after = 0.0
            self._last_error = ""

    # -- refresh ---------------------------------------------------------

    def _refresh_newest(self, timeout_seconds: int) -> None:
        with self._state_lock:
            now = time.monotonic()
            if now < self._retry_after:
                raise GkgError(self._last_error or "GDELT recently failed; retrying shortly.")
            if self._files and now - self._last_poll < _POLL_INTERVAL_SECONDS:
                return
        try:
            text = _download(LASTUPDATE_URL, MAX_LASTUPDATE_BYTES, timeout_seconds).decode(
                "utf-8", errors="replace"
            )
            self._load_slot(parse_lastupdate(text), timeout_seconds)
        except GkgError as exc:
            with self._state_lock:
                self._last_error = str(exc)
                self._retry_after = time.monotonic() + _FAILURE_BACKOFF_SECONDS
            raise
        with self._state_lock:
            self._last_poll = time.monotonic()
            self._retry_after = 0.0

    def _load_slot(self, slot: str, timeout_seconds: int) -> bool:
        """Download + parse one slot unless already held. Returns True if it downloaded."""
        with self._download_lock:  # single-flight: a racing caller finds the slot loaded
            with self._state_lock:
                if slot in self._files:
                    return False
            data = _download(
                _GKG_URL_TEMPLATE.format(ts=slot), MAX_COMPRESSED_BYTES, timeout_seconds
            )
            articles = parse_gkg_zip(data, slot, limit=max_articles())
            with self._state_lock:
                self._files = self._trim({**self._files, slot: articles})
            return True

    @staticmethod
    def _trim(files: dict[str, tuple[Article, ...]]) -> dict[str, tuple[Article, ...]]:
        """Drop slots outside the window, then oldest articles beyond the hard cap."""
        newest = _slot_time(max(files))
        oldest_kept = _slot_str(newest - timedelta(hours=window_hours(), minutes=-1))
        budget = max_articles()
        trimmed: dict[str, tuple[Article, ...]] = {}
        for slot in sorted(files, reverse=True):  # newest slots get the budget first
            if slot < oldest_kept:
                continue
            kept = files[slot][-budget:] if budget > 0 else ()
            if kept:
                trimmed[slot] = kept
            budget -= len(kept)
        return trimmed

    # -- backfill --------------------------------------------------------

    def _ensure_backfill(self, timeout_seconds: int) -> None:
        with self._state_lock:
            if (
                self._backfilling
                or not self._files
                or time.monotonic() < self._backfill_retry_after
            ):
                return
            newest = _slot_time(max(self._files))
            wanted = (
                _slot_str(newest - timedelta(minutes=SLOT_MINUTES * i))
                for i in range(1, window_hours() * 60 // SLOT_MINUTES)
            )
            missing = [slot for slot in wanted if slot not in self._files]
            if not missing:
                return
            self._backfilling = True
        threading.Thread(
            target=self._backfill, args=(missing, timeout_seconds), daemon=True, name="gdelt-gkg"
        ).start()

    def _backfill(self, slots: list[str], timeout_seconds: int) -> None:
        failures = 0
        try:
            for slot in slots:
                try:
                    if self._load_slot(slot, timeout_seconds):
                        time.sleep(_BACKFILL_PAUSE_SECONDS)
                except GkgError as exc:
                    # GDELT occasionally skips a slot (404); a run of failures
                    # means it is down — stop and let a later query retry.
                    failures += 1
                    logger.warning("GDELT GKG backfill of %s failed: %s", slot, exc)
                    if failures >= _BACKFILL_MAX_FAILURES:
                        with self._state_lock:
                            self._backfill_retry_after = time.monotonic() + _FAILURE_BACKOFF_SECONDS
                        break
        finally:
            with self._state_lock:
                self._backfilling = False

    # -- snapshot --------------------------------------------------------

    def _has_recent_data(self) -> bool:
        with self._state_lock:
            newest = _slot_time(max(self._files)) if self._files else None
        return newest is not None and _age_minutes(newest) <= STALE_LIMIT_MINUTES

    def _build_window(self) -> Window:
        with self._state_lock:
            slots = sorted(self._files)
            articles = tuple(a for slot in slots for a in self._files[slot])
            loading = self._backfilling
        newest = _slot_time(slots[-1]) if slots else None
        oldest = _slot_time(slots[0]) if slots else None
        covered = (
            int((newest - oldest).total_seconds() // 60) + SLOT_MINUTES if newest and oldest else 0
        )
        return Window(
            articles=articles,
            covered_minutes=covered,
            window_minutes=window_hours() * 60,
            loading=loading,
            stale_minutes=max(0, _age_minutes(newest) - 2 * SLOT_MINUTES) if newest else 0,
        )


_WINDOW = GkgWindow()


def get_window() -> GkgWindow:
    return _WINDOW
