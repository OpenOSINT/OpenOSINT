"""Tests for the Xquik X search integration."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from openosint.tools.search_x import _raise_for_status, run_x_osint


def _payload() -> dict:
    return {
        "tweets": [
            {
                "id": "123",
                "text": "Market update with useful context",
                "createdAt": "2026-07-10T10:00:00Z",
                "likeCount": 12,
                "retweetCount": 3,
                "replyCount": 2,
                "quoteCount": 1,
                "author": {"username": "analyst", "name": "Market Analyst"},
                "url": "https://x.com/analyst/status/123",
            }
        ],
        "has_next_page": False,
        "next_cursor": "",
    }


async def test_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XQUIK_API_KEY", raising=False)
    result = await run_x_osint("market news")
    assert "XQUIK_API_KEY" in result


@pytest.mark.parametrize(
    ("query", "query_type", "limit", "expected"),
    [
        ("   ", "Latest", 20, "Invalid search query"),
        ("market", "Recent", 20, "Invalid query type"),
        ("market", "Latest", 0, "Invalid result limit"),
        ("market", "Latest", True, "Invalid result limit"),
    ],
)
async def test_rejects_invalid_input(
    query: str,
    query_type: str,
    limit: int,
    expected: str,
) -> None:
    result = await run_x_osint(
        query,
        query_type=query_type,
        limit=limit,
        api_key="test-key",
    )
    assert expected in result


async def test_formats_search_results() -> None:
    fetch = AsyncMock(return_value=_payload())
    with patch("openosint.tools.search_x._fetch_x_data", new=fetch):
        result = await run_x_osint(
            "market news",
            query_type="top",
            limit=2,
            api_key="test-key",
        )

    fetch.assert_awaited_once_with("market news", "test-key", "Top", 2, 30)
    assert "@analyst (Market Analyst)" in result
    assert "likes 12 | reposts 3 | replies 2 | quotes 1" in result
    assert "https://x.com/analyst/status/123" in result


async def test_handles_empty_results() -> None:
    with patch(
        "openosint.tools.search_x._fetch_x_data",
        new=AsyncMock(return_value={"tweets": []}),
    ):
        result = await run_x_osint("no matches", api_key="test-key")
    assert result == "[Xquik] No X posts found for: no matches"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (asyncio.TimeoutError(), "timed out"),
        (aiohttp.ClientError("offline"), "Network error"),
        (ValueError("Xquik: invalid API key."), "invalid API key"),
        (RuntimeError("unexpected"), "Internal error"),
    ],
)
async def test_handles_request_errors(error: Exception, expected: str) -> None:
    with patch(
        "openosint.tools.search_x._fetch_x_data",
        new=AsyncMock(side_effect=error),
    ):
        result = await run_x_osint("market", api_key="test-key")
    assert expected in result


@pytest.mark.parametrize("status", [400, 401, 402, 424, 429, 502, 503])
def test_http_errors_are_mapped(status: int) -> None:
    with pytest.raises(ValueError):
        _raise_for_status(status)


def test_http_200_is_accepted() -> None:
    _raise_for_status(200)


async def test_registered_in_all_interfaces() -> None:
    from openosint.agent import _TOOL_MAP, TOOL_DEFINITIONS
    from openosint.cli import _build_parser
    from openosint.mcp_server import _HANDLERS, list_tools
    from openosint.repl import _TOOL_INFO_ROWS
    from openosint.web_server import _KNOWN_ENV_KEYS, _RUNNERS, _TOOL_CATALOG

    assert "search_x" in {tool["name"] for tool in TOOL_DEFINITIONS}
    assert "search_x" in _TOOL_MAP
    assert "search_x" in {tool.name for tool in await list_tools()}
    assert "search_x" in _HANDLERS
    assert "search_x" in {row[0] for row in _TOOL_INFO_ROWS}
    assert "search_x" in _RUNNERS
    assert "search_x" in {tool["name"] for tool in _TOOL_CATALOG}
    assert "XQUIK_API_KEY" in _KNOWN_ENV_KEYS

    args = _build_parser().parse_args(["x", "market news", "--query-type", "Top", "--limit", "3"])
    assert args.command == "x"
    assert args.query_type == "Top"
    assert args.limit == 3
