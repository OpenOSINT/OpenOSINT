"""OpenOSINT News Monitor — Apify Actor.

Given a keyword query, returns matching real-time global news articles via
the public, keyless GDELT DOC 2.0 API (artlist mode). Monetized via Apify
pay-per-event: one charge per article returned.

This Actor previously used GDELT's GEO 2.0 API (geolocated news mentions),
but that endpoint (api.gdeltproject.org/api/v2/geo/geo) started returning
HTTP 404 for every query — confirmed across many parameter combinations,
including GDELT's own documented example URLs, while this DOC 2.0 endpoint
on the same host continued to work normally. No official GDELT deprecation
notice was found for the GEO API at the time of this change (see the
CHANGELOG/commit for what was checked and where).
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from apify import Actor

from openosint.tools.exceptions import OSINTError, ToolExecutionError
from openosint.tools.search_gdelt_doc import fetch_gdelt_doc_data, parse_articles

# Event name — this MUST match exactly what you configure in the Apify
# Console under Publication > Monetization.
EVENT_NEWS_ARTICLE = "news-article"

_MAX_QUERY_LENGTH = 500
_DEFAULT_TIMESPAN_MINUTES = 60
_MIN_TIMESPAN_MINUTES = 15
_MAX_TIMESPAN_MINUTES = 1440
_MAXRECORDS = 75  # GDELT's own hard cap is 250; kept modest to bound cost per run
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


def clamp_timespan_minutes(value) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = _DEFAULT_TIMESPAN_MINUTES
    return max(_MIN_TIMESPAN_MINUTES, min(_MAX_TIMESPAN_MINUTES, minutes))


async def _respect_rate_limit() -> None:
    """Never issue a GDELT request less than 5s after the previous one."""
    global _last_request_at
    now = time.monotonic()
    wait = _MIN_REQUEST_INTERVAL_SECONDS - (now - _last_request_at)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_request_at = time.monotonic()


async def fetch_with_backoff(query: str, timespan_minutes: int) -> dict:
    """Fetch GDELT DOC data, retrying with backoff (longer after a 429)."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        await _respect_rate_limit()
        try:
            return await asyncio.to_thread(
                fetch_gdelt_doc_data,
                query,
                f"{timespan_minutes}min",
                _MAXRECORDS,
                _REQUEST_TIMEOUT_SECONDS,
            )
        except (OSINTError, ToolExecutionError) as exc:
            last_exc = exc
            if attempt >= _MAX_ATTEMPTS - 1:
                break
            is_rate_limited = "429" in str(exc)
            backoff = _RATE_LIMITED_BACKOFF_SECONDS if is_rate_limited else _BASE_BACKOFF_SECONDS
            Actor.log.warning(
                f"GDELT fetch attempt {attempt + 1} failed — {type(exc).__name__}: {exc!r}; retrying in {backoff}s"
            )
            await asyncio.sleep(backoff)
    raise last_exc


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        query = validate_query(actor_input.get("query"))

        if query is None:
            await Actor.fail(
                status_message=f"Invalid query: must be a non-empty string of at most {_MAX_QUERY_LENGTH} characters."
            )
            return

        timespan_minutes = clamp_timespan_minutes(actor_input.get("timespanMinutes", _DEFAULT_TIMESPAN_MINUTES))

        Actor.log.info(f"Searching GDELT DOC for '{query}' (last {timespan_minutes}min).")

        try:
            data = await fetch_with_backoff(query, timespan_minutes)
        except (OSINTError, ToolExecutionError) as exc:
            await Actor.fail(
                status_message=(
                    f"GDELT DOC search failed after {_MAX_ATTEMPTS} attempt(s): "
                    f"{type(exc).__name__}: {exc!r}"
                )
            )
            return

        articles = parse_articles(data, query, timespan_minutes)
        checked_at = datetime.now(timezone.utc).isoformat()

        total_pushed = 0
        limit_reached = False

        for item in articles:
            if limit_reached:
                break

            item["checkedAt"] = checked_at
            charge_result = await Actor.push_data(item, charged_event_name=EVENT_NEWS_ARTICLE)
            total_pushed += 1

            if charge_result.event_charge_limit_reached:
                Actor.log.info("Charge limit reached — stopping.")
                limit_reached = True

        status = f"{total_pushed} article(s) found for query '{query}'"
        Actor.log.info(status)
        await Actor.set_status_message(status, is_terminal=not limit_reached)
