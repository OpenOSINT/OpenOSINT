"""Tests for openosint/tools/search_gdelt_doc.py — used by the news-monitor Actor.

All network calls (requests.get) are mocked — no real HTTP traffic.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from openosint.tools.exceptions import OSINTError, ToolExecutionError
from openosint.tools.search_gdelt_doc import fetch_gdelt_doc_data, parse_articles

_SAMPLE_RESPONSE = {
    "articles": [
        {
            "url": "https://news.example.test/story/1",
            "url_mobile": "",
            "title": "Example headline about Ukraine",
            "seendate": "20260913T091500Z",
            "socialimage": "",
            "domain": "news.example.test",
            "language": "Romanian",
            "sourcecountry": "",
        },
        {
            "url": "https://uk-news.example.test/article/2",
            "url_mobile": "",
            "title": "Real hardship and difficulties lie ahead",
            "seendate": "20260913T091500Z",
            "socialimage": "https://images.example.test/841550.jpg",
            "domain": "uk-news.example.test",
            "language": "English",
            "sourcecountry": "United Kingdom",
        },
    ]
}


class TestFetchGdeltDocData:
    def test_returns_json_on_200(self):
        with patch("requests.get", return_value=Mock(status_code=200, json=lambda: _SAMPLE_RESPONSE)):
            data = fetch_gdelt_doc_data("ukraine", timespan="60min", maxrecords=75)
        assert data == _SAMPLE_RESPONSE

    def test_raises_osint_error_on_connect_timeout(self):
        with patch("requests.get", side_effect=requests.ConnectTimeout("timed out")):
            with pytest.raises(OSINTError, match="did not respond"):
                fetch_gdelt_doc_data("ukraine", timespan="60min", maxrecords=75)

    def test_raises_osint_error_on_read_timeout(self):
        with patch("requests.get", side_effect=requests.Timeout("timed out")):
            with pytest.raises(OSINTError, match="timed out"):
                fetch_gdelt_doc_data("ukraine", timespan="60min", maxrecords=75)

    def test_raises_tool_execution_error_on_429(self):
        with patch("requests.get", return_value=Mock(status_code=429)):
            with pytest.raises(ToolExecutionError, match="429"):
                fetch_gdelt_doc_data("ukraine", timespan="60min", maxrecords=75)

    def test_raises_tool_execution_error_on_malformed_json(self):
        bad_response = Mock(status_code=200)
        bad_response.json.side_effect = ValueError("bad json")
        with patch("requests.get", return_value=bad_response):
            with pytest.raises(ToolExecutionError, match="malformed JSON"):
                fetch_gdelt_doc_data("ukraine", timespan="60min", maxrecords=75)

    def test_raises_tool_execution_error_on_unexpected_shape(self):
        with patch("requests.get", return_value=Mock(status_code=200, json=lambda: {"unexpected": True})):
            with pytest.raises(ToolExecutionError, match="unexpected response shape"):
                fetch_gdelt_doc_data("ukraine", timespan="60min", maxrecords=75)


class TestParseArticles:
    def test_parses_all_articles_into_flat_rows(self):
        rows = parse_articles(_SAMPLE_RESPONSE, query="ukraine", timespan_minutes=60)
        assert len(rows) == 2
        assert rows[0] == {
            "query": "ukraine",
            "title": "Example headline about Ukraine",
            "url": "https://news.example.test/story/1",
            "domain": "news.example.test",
            "language": "Romanian",
            "sourceCountry": None,
            "seenDate": "20260913T091500Z",
            "timespanMinutes": 60,
        }

    def test_normalizes_empty_source_country_to_none(self):
        rows = parse_articles(_SAMPLE_RESPONSE, query="ukraine", timespan_minutes=60)
        assert rows[0]["sourceCountry"] is None
        assert rows[1]["sourceCountry"] == "United Kingdom"

    def test_empty_articles_list_returns_empty_rows(self):
        assert parse_articles({"articles": []}, query="ukraine", timespan_minutes=60) == []

    def test_no_tone_field_is_fabricated(self):
        rows = parse_articles(_SAMPLE_RESPONSE, query="ukraine", timespan_minutes=60)
        assert "tone" not in rows[0]
