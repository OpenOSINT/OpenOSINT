"""Unit tests for openosint-news-monitor: validation and parsing only.

Network calls (GDELT) are always mocked — these tests never hit the
network or a real Actor run, and never actually sleep for the rate limit.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.main import (
    clamp_timespan_minutes,
    fetch_with_backoff,
    validate_query,
)


class TestValidateQuery:
    def test_accepts_a_normal_query(self):
        assert validate_query("ukraine") == "ukraine"

    def test_strips_whitespace(self):
        assert validate_query("  ukraine  ") == "ukraine"

    def test_rejects_empty_string(self):
        assert validate_query("") is None
        assert validate_query("   ") is None

    def test_rejects_non_string(self):
        assert validate_query(None) is None
        assert validate_query(123) is None

    def test_rejects_overly_long_query(self):
        assert validate_query("a" * 501) is None


class TestClampTimespanMinutes:
    def test_within_range_is_unchanged(self):
        assert clamp_timespan_minutes(120) == 120

    def test_below_minimum_is_raised(self):
        assert clamp_timespan_minutes(1) == 15

    def test_above_maximum_is_lowered(self):
        assert clamp_timespan_minutes(999999) == 1440

    def test_non_numeric_falls_back_to_default(self):
        assert clamp_timespan_minutes("not a number") == 60

    def test_none_falls_back_to_default(self):
        assert clamp_timespan_minutes(None) == 60


class TestFetchWithBackoff:
    async def test_returns_data_on_first_success(self):
        expected = {"articles": []}
        with (
            patch("src.main.fetch_gdelt_doc_data", return_value=expected),
            patch("src.main._respect_rate_limit", new=AsyncMock()),
        ):
            data = await fetch_with_backoff("ukraine", 60)
        assert data == expected

    async def test_retries_then_succeeds(self):
        from openosint.tools.exceptions import ToolExecutionError

        expected = {"articles": []}
        with (
            patch("src.main.fetch_gdelt_doc_data", side_effect=[ToolExecutionError("boom"), expected]),
            patch("src.main._respect_rate_limit", new=AsyncMock()),
            patch("src.main._BASE_BACKOFF_SECONDS", 0),
        ):
            data = await fetch_with_backoff("ukraine", 60)
        assert data == expected

    async def test_retries_longer_after_429(self):
        from openosint.tools.exceptions import ToolExecutionError

        expected = {"articles": []}
        with (
            patch(
                "src.main.fetch_gdelt_doc_data",
                side_effect=[ToolExecutionError("GDELT DOC API returned HTTP 429."), expected],
            ),
            patch("src.main._respect_rate_limit", new=AsyncMock()),
            patch("src.main._RATE_LIMITED_BACKOFF_SECONDS", 0),
        ):
            data = await fetch_with_backoff("ukraine", 60)
        assert data == expected

    async def test_raises_after_max_attempts(self):
        from openosint.tools.exceptions import ToolExecutionError

        with (
            patch("src.main.fetch_gdelt_doc_data", side_effect=ToolExecutionError("still down")),
            patch("src.main._respect_rate_limit", new=AsyncMock()),
            patch("src.main._BASE_BACKOFF_SECONDS", 0),
            patch("src.main._RATE_LIMITED_BACKOFF_SECONDS", 0),
        ):
            with pytest.raises(ToolExecutionError):
                await fetch_with_backoff("ukraine", 60)


class TestChargeLimitStopsTheRun:
    """Proves main() stops pushing/charging further articles once
    Actor.push_data() reports event_charge_limit_reached. The Actor object
    itself is fully mocked so this test never touches real Apify local
    storage or the network."""

    async def test_stops_pushing_once_limit_reached(self):
        from types import SimpleNamespace

        from src.main import main

        mock_actor = MagicMock()
        mock_actor.__aenter__ = AsyncMock(return_value=mock_actor)
        mock_actor.__aexit__ = AsyncMock(return_value=False)
        mock_actor.get_input = AsyncMock(return_value={"query": "ukraine"})
        mock_actor.fail = AsyncMock()
        mock_actor.set_status_message = AsyncMock()

        articles = {
            "articles": [
                {"url": f"https://news{i}.test/a", "title": f"Story {i}", "domain": f"news{i}.test", "language": "English", "sourcecountry": "US", "seendate": "20260913T091500Z"}
                for i in range(5)
            ]
        }
        charge_results = iter(
            [SimpleNamespace(event_charge_limit_reached=False), SimpleNamespace(event_charge_limit_reached=True)]
        )
        mock_actor.push_data = AsyncMock(side_effect=lambda *a, **k: next(charge_results))

        with (
            patch("src.main.Actor", mock_actor),
            patch("src.main.fetch_with_backoff", new=AsyncMock(return_value=articles)),
        ):
            await main()

        assert mock_actor.push_data.call_count == 2
        mock_actor.fail.assert_not_called()
