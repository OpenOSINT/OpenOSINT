"""Search public X posts through the Xquik API."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_API_URL = "https://xquik.com/api/v1/x/tweets/search"
_DEFAULT_TIMEOUT = 30
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 50
_MAX_TEXT_LENGTH = 500

_MISSING_KEY_ERROR = (
    "Scan error: XQUIK_API_KEY environment variable is not set. "
    "Create an API key at https://dashboard.xquik.com"
)


def _raise_for_status(status: int) -> None:
    if status == 400:
        raise ValueError("Xquik: invalid search request.")
    if status == 401:
        raise ValueError("Xquik: invalid API key.")
    if status == 402:
        raise ValueError("Xquik: insufficient credits for this search.")
    if status == 429:
        raise ValueError("Xquik: rate limit exceeded.")
    if status in (424, 502):
        raise ValueError("Xquik: X data service unavailable.")
    if status != 200:
        raise ValueError(f"Xquik returned HTTP {status}.")


async def _fetch_x_data(
    query: str,
    api_key: str,
    query_type: str,
    limit: int,
    timeout: int,
) -> dict[str, Any]:
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    params = {"q": query, "queryType": query_type, "limit": str(limit)}
    timeout_config = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout_config) as session:
        async with session.get(_API_URL, headers=headers, params=params) as response:
            _raise_for_status(response.status)
            payload = await response.json(content_type=None)
            if not isinstance(payload, dict):
                raise ValueError("Xquik returned an invalid response.")
            return payload


def _clean_text(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= _MAX_TEXT_LENGTH:
        return text
    return f"{text[: _MAX_TEXT_LENGTH - 3]}..."


def _format_results(payload: dict[str, Any], query: str) -> str:
    raw_tweets = payload.get("tweets")
    if not isinstance(raw_tweets, list) or not raw_tweets:
        return f"[Xquik] No X posts found for: {_clean_text(query)}"

    lines = [f"[Xquik] X search: {_clean_text(query)}"]
    result_count = 0
    for raw_tweet in raw_tweets:
        if not isinstance(raw_tweet, dict):
            continue
        result_count += 1
        author_value = raw_tweet.get("author")
        author = author_value if isinstance(author_value, dict) else {}
        username = _clean_text(author.get("username")) or "unknown"
        name = _clean_text(author.get("name")) or username
        created_at = _clean_text(raw_tweet.get("createdAt")) or "unknown time"
        tweet_id = _clean_text(raw_tweet.get("id"))
        permalink = _clean_text(raw_tweet.get("url"))
        if not permalink and tweet_id and username != "unknown":
            permalink = f"https://x.com/{username}/status/{tweet_id}"

        lines.extend(
            [
                "",
                f"{result_count}. @{username} ({name}) | {created_at}",
                f"Text: {_clean_text(raw_tweet.get('text'))}",
                (
                    f"Engagement: likes {raw_tweet.get('likeCount', 0)} | "
                    f"reposts {raw_tweet.get('retweetCount', 0)} | "
                    f"replies {raw_tweet.get('replyCount', 0)} | "
                    f"quotes {raw_tweet.get('quoteCount', 0)}"
                ),
            ]
        )
        if permalink:
            lines.append(f"URL: {permalink}")

    if result_count == 0:
        return f"[Xquik] No X posts found for: {_clean_text(query)}"
    return "\n".join(lines)


async def run_x_osint(
    query: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
    *,
    query_type: str = "Latest",
    limit: int = _DEFAULT_LIMIT,
    api_key: str | None = None,
) -> str:
    """Search public X posts by query. Requires XQUIK_API_KEY."""
    resolved_key = (api_key or os.environ.get("XQUIK_API_KEY", "")).strip()
    if not resolved_key:
        return _MISSING_KEY_ERROR

    normalized_query = " ".join(query.split())
    if not normalized_query:
        return "Invalid search query: enter at least one non-whitespace character."

    query_types = {"latest": "Latest", "top": "Top"}
    normalized_type = query_types.get(query_type.strip().lower())
    if normalized_type is None:
        return "Invalid query type: use Latest or Top."
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_LIMIT:
        return f"Invalid result limit: use an integer from 1 to {_MAX_LIMIT}."

    try:
        payload = await _fetch_x_data(
            normalized_query,
            resolved_key,
            normalized_type,
            limit,
            timeout_seconds,
        )
        return _format_results(payload, normalized_query)
    except asyncio.TimeoutError:
        return f"Scan error: Xquik request timed out after {timeout_seconds}s."
    except aiohttp.ClientError:
        return "Scan error: Network error querying Xquik."
    except ValueError as exc:
        return f"Scan error: {exc}"
    except Exception:
        logger.exception("Unexpected error during Xquik X search.")
        return "Internal error: Xquik X search failed."
