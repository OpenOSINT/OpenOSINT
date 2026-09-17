"""Unit tests for openosint-news-geo: validation and parsing only.

Network calls (GDELT) are always mocked — these tests never hit the
network or a real Actor run, and never actually sleep for the rate limit.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.main import (
    extract_geo_results,
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


class TestExtractGeoResults:
    def test_parses_features_into_flat_rows(self):
        feature_collection = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [30.52, 50.45]},
                    "properties": {"name": "Kyiv, Ukraine", "count": 12, "html": '<a href="https://a.com">x</a>'},
                }
            ],
        }
        results = extract_geo_results(feature_collection, query="ukraine", timespan=60)
        assert results == [
            {
                "query": "ukraine",
                "locationName": "Kyiv, Ukraine",
                "lat": 50.45,
                "lon": 30.52,
                "articleCount": 12,
                "sampleUrls": ["https://a.com"],
                "timespanMinutes": 60,
            }
        ]

    def test_skips_features_without_coordinates(self):
        feature_collection = {"features": [{"geometry": {}, "properties": {}}]}
        assert extract_geo_results(feature_collection, query="x", timespan=60) == []

    def test_empty_feature_collection_returns_empty_list(self):
        assert extract_geo_results({"features": []}, query="x", timespan=60) == []


class TestFetchWithBackoff:
    async def test_returns_data_on_first_success(self):
        expected = {"type": "FeatureCollection", "features": []}
        with (
            patch("src.main.fetch_gdelt_data", return_value=expected),
            patch("src.main._respect_rate_limit", new=AsyncMock()),
        ):
            data = await fetch_with_backoff("ukraine", 60, 250)
        assert data == expected

    async def test_retries_then_succeeds(self):
        from openosint.tools.exceptions import ToolExecutionError

        expected = {"type": "FeatureCollection", "features": []}
        with (
            patch("src.main.fetch_gdelt_data", side_effect=[ToolExecutionError("boom"), expected]),
            patch("src.main._respect_rate_limit", new=AsyncMock()),
            patch("src.main._BASE_BACKOFF_SECONDS", 0),
        ):
            data = await fetch_with_backoff("ukraine", 60, 250)
        assert data == expected

    async def test_raises_after_max_attempts(self):
        from openosint.tools.exceptions import ToolExecutionError

        with (
            patch("src.main.fetch_gdelt_data", side_effect=ToolExecutionError("still down")),
            patch("src.main._respect_rate_limit", new=AsyncMock()),
            patch("src.main._BASE_BACKOFF_SECONDS", 0),
            patch("src.main._RATE_LIMITED_BACKOFF_SECONDS", 0),
        ):
            with pytest.raises(ToolExecutionError):
                await fetch_with_backoff("ukraine", 60, 250)
