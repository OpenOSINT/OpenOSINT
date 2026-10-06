# openosint/tools/search_gdelt_geo.py
"""
Geolocated worldwide news search over GDELT's 15-minute GKG feed.

The GDELT GEO 2.0 API this tool used to call was retired (HTTP 404), so
articles now come from the GKG files GDELT publishes every 15 minutes (keyless,
no account), held in a rolling in-memory window by openosint.tools.gdelt_gkg.
Nothing is downloaded until this tool is first called.

Returns a formatted string; never raises. The GeoJSON FeatureCollection the
globe draws is embedded as a fenced ```geojson block at the end of the string
(same string-only contract every other tool follows) so the web UI can pull it
back out without a second round trip. Article titles/URLs are third-party text:
they appear only inside that fence (browser-bound, rendered as text) and never
in the model-bound summary.

Data: GDELT Project, https://www.gdeltproject.org/ (free for any use with
citation; see the README).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from openosint.tools.gdelt_gkg import (
    SLOT_MINUTES,
    Article,
    GkgError,
    Window,
    get_window,
)

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 15
_MIN_TIMESPAN = 15
_MAX_TIMESPAN = 1440
_DEFAULT_TIMESPAN = 60
_MAX_MAXPOINTS = 500
_DEFAULT_MAXPOINTS = 250
_SAMPLE_LINES = 10
_MAX_QUERY_CHARS = 200
_MAX_QUERY_TERMS = 10
_PLACES_PER_ARTICLE_ON_MAP = 3  # an article about 5 countries is not 5 dots
_MATCH_ALL = {"", "*"}

BBox = tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)

SERVICE_UNAVAILABLE_MARKER = "[service_unavailable] search_gdelt_geo"


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


# --------------------------------------------------------------------------
# Query matching
# --------------------------------------------------------------------------

_TERM_RE = re.compile(r'"([^"]+)"|(\S+)')


def parse_query(query: str) -> list[list[str]]:
    """'a "b c" OR d' → [['a', 'b c'], ['d']]: OR of ANDs, lower-cased. [] matches everything."""
    text = query.strip()[:_MAX_QUERY_CHARS]
    if text in _MATCH_ALL:
        return []
    groups = []
    for chunk in re.split(r"\s+OR\s+", text):
        terms = [(m.group(1) or m.group(2)).lower().strip("()") for m in _TERM_RE.finditer(chunk)]
        terms = [t for t in terms if t]
        if terms:
            groups.append(terms[:_MAX_QUERY_TERMS])
    return groups


def _matches(article: Article, groups: list[list[str]]) -> bool:
    if not groups:
        return True
    haystack = f"{article.title} {article.url}".lower()
    return any(all(term in haystack for term in group) for group in groups)


def _in_bbox(lon: float, lat: float, bbox: BBox) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    if not min_lat <= lat <= max_lat:
        return False
    if min_lon <= max_lon:
        return min_lon <= lon <= max_lon
    return lon >= min_lon or lon <= max_lon  # box crosses the antimeridian


def parse_bbox(raw) -> BBox | None:
    """Validate a user/agent supplied bbox: None for 'no bbox', ValueError when malformed."""
    if raw is None or raw == "" or raw == [] or raw == ():
        return None
    try:
        values = tuple(float(v) for v in raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("bbox must be four numbers") from exc
    if len(values) != 4:
        raise ValueError("bbox must be [min_lon, min_lat, max_lon, max_lat]")
    min_lon, min_lat, max_lon, max_lat = values
    if not (-90 <= min_lat <= max_lat <= 90 and -180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        raise ValueError("bbox is out of range (lat -90..90, lon -180..180, min_lat <= max_lat)")
    return min_lon, min_lat, max_lon, max_lat


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


@dataclass
class _Spot:
    name: str
    lat: float
    lon: float
    lead: Article
    count: int = 0
    tone_sum: float = 0.0


def build_feature_collection(
    articles: tuple[Article, ...],
    groups: list[list[str]],
    cutoff_slot: str,
    bbox: BBox | None,
    maxpoints: int,
) -> dict:
    """Group matching articles by place into Point features (busiest first)."""
    spots: dict[tuple[float, float], _Spot] = {}
    for article in reversed(articles):  # newest first, so each spot's lead article is the newest
        if article.slot < cutoff_slot or not _matches(article, groups):
            continue
        for place in article.places[:_PLACES_PER_ARTICLE_ON_MAP]:
            if bbox and not _in_bbox(place.lon, place.lat, bbox):
                continue
            spot = spots.setdefault(
                (place.lat, place.lon), _Spot(place.name, place.lat, place.lon, article)
            )
            spot.count += 1
            spot.tone_sum += article.tone
    busiest = sorted(spots.values(), key=lambda s: -s.count)[:maxpoints]
    features = [
        {
            "type": "Feature",
            "properties": {
                "name": spot.name,
                "count": spot.count,
                "title": spot.lead.title,
                "url": spot.lead.url,
                "domain": spot.lead.domain,
                "tone": round(spot.tone_sum / spot.count, 1),
            },
            "geometry": {"type": "Point", "coordinates": [spot.lon, spot.lat]},
        }
        for spot in busiest
    ]
    return {"type": "FeatureCollection", "features": features}


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

_GEOJSON_FENCE_RE = re.compile(r"```geojson\n(.*?)```", re.DOTALL)


def split_geojson_fence(output: str) -> tuple[str, str | None]:
    """Split a search_gdelt_geo result into (text_for_model, raw_geojson).

    The fenced ```geojson block exists so the browser can pull the raw
    FeatureCollection out over SSE and hand it to the globe. The LLM has no
    use for raw coordinates (nor for third-party headlines), and every call
    site that feeds a tool result back to a provider resends the *entire*
    conversation on every subsequent round — an unstripped fence costs real
    tokens on every round after the one that called this tool. Every
    model-bound call site must call this first; every browser/SSE-bound call
    site must keep the original string.

    Returns (output, None) unchanged when no fence is present — safe to
    call on any tool's output, not just search_gdelt_geo's.
    """
    match = _GEOJSON_FENCE_RE.search(output)
    if not match:
        return output, None

    geojson = match.group(1)
    try:
        feature_count = len(json.loads(geojson).get("features", []))
    except (json.JSONDecodeError, AttributeError, TypeError):
        feature_count = 0

    text = output[: match.start()].rstrip() + f"\n\n[{feature_count} geo point(s) → globe]"
    return text, geojson


def _duration(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} h" if not rest else f"{hours} h {rest} min"


def _coverage(window: Window, timespan: int) -> dict:
    requested = min(timespan, window.window_minutes)
    return {
        "minutes": min(requested, window.covered_minutes),
        "requested": requested,
        "loading": window.loading and window.covered_minutes < requested,
        "stale_minutes": window.stale_minutes,
    }


def _coverage_note(coverage: dict) -> str:
    note = f"Coverage: the last {_duration(coverage['minutes'])}"
    if coverage["minutes"] < coverage["requested"]:
        note += f" (of the {_duration(coverage['requested'])} requested"
        note += (
            "; older articles are still loading, search again shortly)"
            if coverage["loading"]
            else ")"
        )
    if coverage["stale_minutes"]:
        note += f". Data is {_duration(coverage['stale_minutes'])} behind: GDELT did not refresh"
    return note + "."


def _format_results(fc: dict, query: str, coverage: dict) -> str:
    features = fc["features"]
    note = _coverage_note(coverage)
    if not features:
        return f"No geolocated coverage found for '{query}'. {note}"

    mentions = sum(f["properties"]["count"] for f in features)
    lines = [
        f"GDELT geolocated news for '{query}': {len(features)} location(s), "
        f"{mentions} article mention(s). {note}\n"
    ]
    for feat in features[:_SAMPLE_LINES]:
        props = feat["properties"]
        lon, lat = feat["geometry"]["coordinates"]
        lines.append(f"[+] {props['name']} ({lat}, {lon}) — {props['count']} article(s)")
    if len(features) > _SAMPLE_LINES:
        lines.append(f"\n... and {len(features) - _SAMPLE_LINES} more.")
    lines += ["", "```geojson", json.dumps({**fc, "coverage": coverage}), "```"]
    return "\n".join(lines)


def service_unavailable_message(reason: str) -> str:
    """The one result returned when the news feed fails; web/static/geo-extractor.js matches the marker."""
    return (
        "Scan error: GDELT GEO service unavailable, try again later.\n"
        f"{SERVICE_UNAVAILABLE_MARKER}\n"
        f"Reason: {reason}\n"
        "Other tools are unaffected; the news layer on the globe stays empty until GDELT recovers."
    )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _cutoff_slot(articles: tuple[Article, ...], timespan: int) -> str:
    """First slot inside the lookback, measured back from the newest loaded slot."""
    if not articles:
        return ""
    newest = datetime.strptime(max(a.slot for a in articles), "%Y%m%d%H%M%S")
    return (newest - timedelta(minutes=timespan - SLOT_MINUTES)).strftime("%Y%m%d%H%M%S")


async def run_gdelt_geo_osint(
    query: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
    *,
    timespan: int = _DEFAULT_TIMESPAN,
    maxpoints: int = _DEFAULT_MAXPOINTS,
    bbox: BBox | None = None,
) -> str:
    """
    Search worldwide geolocated news coverage for query via GDELT's GKG feed.

    Returns a descriptive error string on failure rather than raising.

    Parameters
    ----------
    query:
        Keywords matched against article headlines and URLs. Quoted phrases and
        OR groups are supported; "*" (or empty) matches everything, which is
        the way to list all coverage inside a bbox.
    timeout_seconds:
        Per-download read timeout.
    timespan:
        Lookback in minutes, clamped to [15, 1440] and to the loaded window
        (OPENOSINT_GDELT_WINDOW_HOURS, default 6 h).
    maxpoints:
        Maximum number of point features, clamped to [1, 500].
    bbox:
        Optional (min_lon, min_lat, max_lon, max_lat); only places inside it.

    Returns
    -------
    str
        Formatted summary + a trailing fenced ```geojson block containing the
        FeatureCollection (with a "coverage" member saying how far back the
        results reach), or a descriptive error message.
    """
    try:
        timespan = _clamp(int(timespan), _MIN_TIMESPAN, _MAX_TIMESPAN)
        maxpoints = _clamp(int(maxpoints), 1, _MAX_MAXPOINTS)
        box = parse_bbox(bbox)
    except (TypeError, ValueError) as exc:
        return f"Invalid input: {exc}"

    logger.info("Starting GDELT geo search for: %s", query)
    try:
        window = await asyncio.to_thread(get_window().snapshot, timeout_seconds)
        coverage = _coverage(window, timespan)
        fc = build_feature_collection(
            window.articles,
            parse_query(query),
            _cutoff_slot(window.articles, coverage["requested"]),
            box,
            maxpoints,
        )
        logger.info("GDELT geo search complete for: %s", query)
        return _format_results(fc, query, coverage)
    except GkgError as exc:
        # Every failure — network, size caps, bad archive, stale data — becomes
        # one structured, human-readable result the UI can recognise.
        logger.warning("GDELT geo search failed: %s", exc)
        return service_unavailable_message(str(exc))
    except Exception as exc:
        logger.exception("Unexpected error during GDELT geo search.")
        return f"Internal error: {exc}"
