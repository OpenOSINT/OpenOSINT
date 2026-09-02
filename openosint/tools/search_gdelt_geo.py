# openosint/tools/search_gdelt_geo.py
"""
GDELT GEO 2.0 geospatial news search module.

Queries the GDELT GEO 2.0 API for real-time, geolocated worldwide news
coverage. Keyless, no auth. Returns a formatted string; never raises.

The raw GeoJSON FeatureCollection is embedded as a fenced ```geojson block
at the end of the string (same string-only contract every other tool
follows) so the web UI's globe view can pull it back out and hand it to
MapLibre without a second round trip.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import requests

from openosint.proxy import get_requests_proxies
from openosint.tools.exceptions import OSINTError, ToolExecutionError

logger = logging.getLogger(__name__)

_GDELT_URL = "https://api.gdeltproject.org/api/v2/geo/geo"
_DEFAULT_TIMEOUT = 15
_MIN_TIMESPAN = 15
_MAX_TIMESPAN = 1440
_DEFAULT_TIMESPAN = 60
_MAX_MAXPOINTS = 500
_DEFAULT_MAXPOINTS = 250
_SAMPLE_LINES = 10
_CACHE_TTL_SECONDS = 300  # GDELT itself only refreshes every 15min upstream

BBox = tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)

# ponytail: process-local dict, single-worker assumption. Move to a shared
# cache (redis, etc.) if this ever runs behind multiple worker processes.
_cache: dict[tuple, tuple[float, dict]] = {}


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _cache_get(key: tuple) -> dict | None:
    hit = _cache.get(key)
    if hit is None:
        return None
    stored_at, data = hit
    if time.monotonic() - stored_at > _CACHE_TTL_SECONDS:
        del _cache[key]
        return None
    return data


def _cache_set(key: tuple, data: dict) -> None:
    _cache[key] = (time.monotonic(), data)


def _in_bbox(lon: float, lat: float, bbox: BBox) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def _filter_by_bbox(feature_collection: dict, bbox: BBox | None) -> dict:
    """Return a copy of feature_collection with only features inside bbox."""
    if not bbox:
        return feature_collection
    kept = []
    for feat in feature_collection.get("features", []):
        coords = (feat.get("geometry") or {}).get("coordinates")
        if not coords or len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]
        if _in_bbox(lon, lat, bbox):
            kept.append(feat)
    return {**feature_collection, "features": kept}


def _fetch_gdelt_data(query: str, timespan: int, maxpoints: int, timeout_seconds: int) -> dict:
    """
    Query the GDELT GEO 2.0 API for point-level geolocated news coverage.

    Raises
    ------
    OSINTError
        On network failures or a timeout.
    ToolExecutionError
        On a non-200 status or a malformed/unexpected response body.
    """
    params = {
        "query": query,
        "mode": "PointData",
        "format": "GeoJSON",
        "timespan": timespan,
        "maxpoints": maxpoints,
    }
    try:
        response = requests.get(
            _GDELT_URL,
            params=params,
            timeout=timeout_seconds,
            proxies=get_requests_proxies(),
        )
    except requests.Timeout as exc:
        raise OSINTError(f"GDELT GEO API timed out after {timeout_seconds}s.") from exc
    except requests.RequestException as exc:
        raise OSINTError(f"Network error querying GDELT GEO API: {exc}") from exc

    if response.status_code != 200:
        raise ToolExecutionError(
            f"GDELT GEO API returned HTTP {response.status_code} — the endpoint is "
            "intermittently unavailable and rate-sensitive; retry shortly."
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise ToolExecutionError("GDELT GEO API returned malformed JSON.") from exc

    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise ToolExecutionError("GDELT GEO API returned an unexpected response shape.")

    return data


_GEOJSON_FENCE_RE = re.compile(r"```geojson\n(.*?)```", re.DOTALL)


def split_geojson_fence(output: str) -> tuple[str, str | None]:
    """Split a search_gdelt_geo result into (text_for_model, raw_geojson).

    The fenced ```geojson block exists so the browser can pull the raw
    FeatureCollection out over SSE and hand it to the globe. The LLM has no
    use for raw coordinates, and every call site that feeds a tool result
    back to a provider resends the *entire* conversation on every
    subsequent round — an unstripped fence costs real tokens (tens of
    thousands, on a BYOK user's own key) on every round after the one that
    called this tool. Every model-bound call site must call this first;
    every browser/SSE-bound call site must keep the original string.

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


def _format_gdelt_results(feature_collection: dict, query: str, timespan: int) -> str:
    """Return a structured string summarising results, plus the raw GeoJSON fence."""
    features = feature_collection.get("features", [])
    if not features:
        return f"No geolocated coverage found for '{query}' in the last {timespan} minute(s)."

    lines = [
        f"GDELT geo results for '{query}' (last {timespan}min): "
        f"{len(features)} location(s)\n"
    ]
    for feat in features[:_SAMPLE_LINES]:
        props = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or [None, None]
        lon, lat = coords[0], coords[1]
        name = props.get("name") or f"{lat}, {lon}"
        count = props.get("count")
        suffix = f" — {count} mention(s)" if count else ""
        lines.append(f"[+] {name} ({lat}, {lon}){suffix}")
    if len(features) > _SAMPLE_LINES:
        lines.append(f"\n... and {len(features) - _SAMPLE_LINES} more.")

    lines.append("")
    lines.append("```geojson")
    lines.append(json.dumps(feature_collection))
    lines.append("```")
    return "\n".join(lines)


async def run_gdelt_geo_osint(
    query: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
    *,
    timespan: int = _DEFAULT_TIMESPAN,
    maxpoints: int = _DEFAULT_MAXPOINTS,
    bbox: BBox | None = None,
) -> str:
    """
    Search worldwide geolocated news coverage for query via GDELT GEO 2.0.

    Returns a descriptive error string on failure rather than raising.

    Parameters
    ----------
    query:
        Keywords to search for. Supports quoted phrases and OR groups.
    timeout_seconds:
        HTTP request timeout in seconds.
    timespan:
        Lookback window in minutes, clamped to [15, 1440].
    maxpoints:
        Maximum number of point features to request, clamped to [1, 500].
    bbox:
        Optional (min_lon, min_lat, max_lon, max_lat). When set, features
        outside it are filtered out server-side before returning.

    Returns
    -------
    str
        Formatted summary + a trailing fenced ```geojson block containing
        the raw FeatureCollection, or a descriptive error message.
    """
    timespan = _clamp(int(timespan), _MIN_TIMESPAN, _MAX_TIMESPAN)
    maxpoints = _clamp(int(maxpoints), 1, _MAX_MAXPOINTS)
    cache_key = (query, timespan, maxpoints)

    logger.info("Starting GDELT geo search for: %s", query)
    try:
        data = _cache_get(cache_key)
        if data is None:
            data = await asyncio.to_thread(
                _fetch_gdelt_data, query, timespan, maxpoints, timeout_seconds
            )
            _cache_set(cache_key, data)
        data = _filter_by_bbox(data, bbox)
        result = _format_gdelt_results(data, query, timespan)
        logger.info("GDELT geo search complete for: %s", query)
        return result
    except OSINTError as exc:
        logger.warning("GDELT geo search failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during GDELT geo search.")
        return f"Internal error: {exc}"
