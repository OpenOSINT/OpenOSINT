"""GDELT DOC 2.0 API news search module.

Queries the DOC 2.0 API (artlist mode) for real-time global news coverage
matching a keyword query. Keyless, public, no auth — the same GDELT Project
API family as search_gdelt_geo.py's GEO 2.0 endpoint, which as of this
writing (2026-09) returns HTTP 404 for every query while this DOC endpoint
still works normally; see CHANGELOG/commit history for what was checked.

No formatted-string wrapper is provided here (unlike most other tools in
this package) — nothing in this repo's CLI/MCP surface consumes DOC search
yet. Add a run_gdelt_doc_osint() the same way search_gdelt_geo.py did, if
that changes.
"""

from __future__ import annotations

import logging

import requests

from openosint.tools.exceptions import OSINTError, ToolExecutionError

logger = logging.getLogger(__name__)

_GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
_DEFAULT_TIMEOUT = 15
_CONNECT_TIMEOUT_SECONDS = 5  # fail fast on a dead/hanging endpoint; read keeps the full budget


def fetch_gdelt_doc_data(
    query: str,
    timespan: str,
    maxrecords: int,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
) -> dict:
    """
    Query the GDELT DOC 2.0 API (artlist mode, JSON) for matching news articles.

    Parameters
    ----------
    query:
        Keywords to search for. Supports quoted phrases and OR groups.
    timespan:
        GDELT's own timespan syntax: a number immediately followed by a unit
        letter, e.g. "60min", "24h", "7d".
    maxrecords:
        Maximum articles to request (GDELT's own hard cap is 250).

    Raises
    ------
    OSINTError
        On network failures or a timeout.
    ToolExecutionError
        On a non-200 status (429 included) or a malformed/unexpected response body.
    """
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "timespan": timespan,
        "maxrecords": maxrecords,
        "sort": "DateDesc",
    }
    try:
        response = requests.get(
            _GDELT_DOC_URL,
            params=params,
            timeout=(_CONNECT_TIMEOUT_SECONDS, timeout_seconds),
        )
    except requests.ConnectTimeout as exc:
        raise OSINTError(
            f"GDELT DOC API did not respond within {_CONNECT_TIMEOUT_SECONDS}s — endpoint appears down."
        ) from exc
    except requests.Timeout as exc:
        raise OSINTError(f"GDELT DOC API timed out after {timeout_seconds}s.") from exc
    except requests.RequestException as exc:
        raise OSINTError(f"Network error querying GDELT DOC API: {exc}") from exc

    if response.status_code != 200:
        raise ToolExecutionError(f"GDELT DOC API returned HTTP {response.status_code}.")

    try:
        data = response.json()
    except ValueError as exc:
        raise ToolExecutionError("GDELT DOC API returned malformed JSON.") from exc

    if not isinstance(data, dict) or "articles" not in data:
        raise ToolExecutionError("GDELT DOC API returned an unexpected response shape.")

    return data


def parse_articles(data: dict, query: str, timespan_minutes: int) -> list[dict]:
    """
    Turn a raw DOC 2.0 artlist response into flat rows.

    GDELT's artlist mode does not expose a per-article tone/sentiment field
    (that's only available via its separate timeline/tonechart modes), so no
    tone field is produced here rather than fabricating one.
    """
    rows = []
    for article in data.get("articles", []):
        rows.append(
            {
                "query": query,
                "title": article.get("title") or None,
                "url": article.get("url") or None,
                "domain": article.get("domain") or None,
                "language": article.get("language") or None,
                "sourceCountry": article.get("sourcecountry") or None,
                "seenDate": article.get("seendate") or None,
                "timespanMinutes": timespan_minutes,
            }
        )
    return rows
