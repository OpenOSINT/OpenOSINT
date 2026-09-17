"""OpenOSINT News Geo — Apify Actor.

Given a keyword query, returns real-time geolocated news mentions worldwide
via the public, keyless GDELT GEO 2.0 API. Monetized via Apify pay-per-event:
one charge per geolocated result returned.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from apify import Actor

from openosint.tools.exceptions import OSINTError, ToolExecutionError
from openosint.tools.search_gdelt_geo import (
    clamp_gdelt_params,
    extract_urls_from_popup_html,
    fetch_gdelt_data,
)

# Event name — this MUST match exactly what you configure in the Apify
# Console under Publication > Monetization.
EVENT_GEO_LOCATION_RESULT = "geo-location-result"

_MAX_QUERY_LENGTH = 500
_DEFAULT_TIMESPAN_MINUTES = 60
_DEFAULT_MAXPOINTS = 250
_REQUEST_TIMEOUT_SECONDS = 15

# GDELT rate limit: at most 1 request per 5 seconds, with backoff on HTTP 429.
_MIN_REQUEST_INTERVAL_SECONDS = 5
_MAX_ATTEMPTS = 4
_BASE_BACKOFF_SECONDS = 5
_RATE_LIMITED_BACKOFF_SECONDS = 20

_last_request_at = 0.0


def validate_query(raw) -> str | None:
    """Return a cleaned query string, or None if it's empty/too long."""
    if not isinstance(raw, str):
        return None
    query = raw.strip()
    if not query or len(query) > _MAX_QUERY_LENGTH:
        return None
    return query


async def _respect_rate_limit() -> None:
    """Never issue a GDELT request less than 5s after the previous one."""
    global _last_request_at
    now = time.monotonic()
    wait = _MIN_REQUEST_INTERVAL_SECONDS - (now - _last_request_at)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_request_at = time.monotonic()


async def fetch_with_backoff(query: str, timespan: int, maxpoints: int) -> dict:
    """Fetch GDELT GEO data, retrying with backoff (longer after a 429)."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        await _respect_rate_limit()
        try:
            return await asyncio.to_thread(
                fetch_gdelt_data, query, timespan, maxpoints, _REQUEST_TIMEOUT_SECONDS
            )
        except (OSINTError, ToolExecutionError) as exc:
            last_exc = exc
            if attempt >= _MAX_ATTEMPTS - 1:
                break
            is_rate_limited = "429" in str(exc)
            backoff = _RATE_LIMITED_BACKOFF_SECONDS if is_rate_limited else _BASE_BACKOFF_SECONDS
            Actor.log.warning(f"GDELT fetch attempt {attempt + 1} failed ({exc}); retrying in {backoff}s")
            await asyncio.sleep(backoff)
    raise last_exc


def extract_geo_results(feature_collection: dict, query: str, timespan: int) -> list[dict]:
    """Turn a GDELT GeoJSON FeatureCollection into flat result rows."""
    results = []
    for feature in feature_collection.get("features", []):
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]
        props = feature.get("properties") or {}
        results.append(
            {
                "query": query,
                "locationName": props.get("name") or f"{lat}, {lon}",
                "lat": lat,
                "lon": lon,
                "articleCount": props.get("count"),
                "sampleUrls": extract_urls_from_popup_html(props.get("html")),
                "timespanMinutes": timespan,
            }
        )
    return results


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        query = validate_query(actor_input.get("query"))

        if query is None:
            Actor.log.error(
                f"Invalid query: must be a non-empty string of at most {_MAX_QUERY_LENGTH} characters."
            )
            return

        timespan, maxpoints = clamp_gdelt_params(
            actor_input.get("timespanMinutes", _DEFAULT_TIMESPAN_MINUTES),
            _DEFAULT_MAXPOINTS,
        )

        Actor.log.info(f"Searching GDELT GEO for '{query}' (last {timespan}min).")

        try:
            feature_collection = await fetch_with_backoff(query, timespan, maxpoints)
        except (OSINTError, ToolExecutionError) as exc:
            Actor.log.error(f"GDELT GEO search failed after {_MAX_ATTEMPTS} attempt(s): {exc}")
            return

        results = extract_geo_results(feature_collection, query, timespan)
        checked_at = datetime.now(timezone.utc).isoformat()

        total_pushed = 0
        limit_reached = False

        for item in results:
            if limit_reached:
                break

            item["checkedAt"] = checked_at
            charge_result = await Actor.push_data(item, charged_event_name=EVENT_GEO_LOCATION_RESULT)
            total_pushed += 1

            if charge_result.event_charge_limit_reached:
                Actor.log.info("Charge limit reached — stopping.")
                limit_reached = True

        status = f"{total_pushed} geolocated result(s) found for query '{query}'"
        Actor.log.info(status)
        await Actor.set_status_message(status, is_terminal=not limit_reached)
