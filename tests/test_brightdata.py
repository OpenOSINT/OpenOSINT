# tests/test_brightdata.py
"""
Unit tests for the Bright Data integration tools:
  - search_dorks_live (openosint/tools/search_dorks_live.py)
  - scrape_url        (openosint/tools/scrape_url.py)

All HTTP calls are mocked — no real network requests are made.

Mock shapes match the verified API behaviour:
  SERP (format=raw, data_format=parsed_light): response.json() → {"organic": [...]}
  Web Unlocker (format=raw, data_format=markdown): response.text → "<markdown string>"
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_serp_response(status_code: int, json_body: dict | None = None) -> MagicMock:
    """Mock for SERP calls: response.json() returns parsed SERP data."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    return resp


def _mock_unlocker_response(status_code: int, text: str = "") -> MagicMock:
    """Mock for Web Unlocker calls: response.text returns the markdown body directly."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# search_dorks_live
# ---------------------------------------------------------------------------


class TestSearchDorksLive:
    async def test_missing_api_key_returns_error_string(self, monkeypatch):
        monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
        monkeypatch.delenv("BRIGHTDATA_SERP_ZONE", raising=False)
        from openosint.tools.search_dorks_live import run_dorks_live_osint

        result = await run_dorks_live_osint("john doe")
        assert "BRIGHTDATA_API_KEY" in result
        assert "5,000" in result
        assert "get.brightdata.com" in result

    async def test_missing_zone_returns_error_string(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.delenv("BRIGHTDATA_SERP_ZONE", raising=False)
        from openosint.tools.search_dorks_live import run_dorks_live_osint

        result = await run_dorks_live_osint("john doe")
        assert "BRIGHTDATA_SERP_ZONE" in result
        assert "get.brightdata.com" in result

    async def test_does_not_raise_on_missing_key(self, monkeypatch):
        monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
        monkeypatch.delenv("BRIGHTDATA_SERP_ZONE", raising=False)
        from openosint.tools.search_dorks_live import run_dorks_live_osint

        result = await run_dorks_live_osint("target")
        assert isinstance(result, str)

    async def test_empty_target_returns_error_string(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")
        from openosint.tools.search_dorks_live import run_dorks_live_osint

        result = await run_dorks_live_osint("   ")
        assert "invalid" in result.lower() or "empty" in result.lower()

    async def test_success_returns_structured_results(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")

        # format="raw" + data_format="parsed_light": response.json() is the dict directly
        serp_payload = {
            "organic": [
                {
                    "title": "John Doe LinkedIn",
                    "link": "https://linkedin.com/in/johndoe",
                    "description": "Software engineer at Acme Corp.",
                },
            ]
        }
        mock_resp = _mock_serp_response(200, serp_payload)

        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            from openosint.tools.search_dorks_live import run_dorks_live_osint

            result = await run_dorks_live_osint("john doe", max_dorks=1)

        assert len(result) == 1
        assert result[0]["results"][0]["title"] == "John Doe LinkedIn"
        assert result[0]["results"][0]["url"] == "https://linkedin.com/in/johndoe"
        assert "Software engineer" in result[0]["results"][0]["snippet"]

    async def test_success_result_contains_dork_header(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")

        mock_resp = _mock_serp_response(200, {"organic": []})
        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            from openosint.tools.search_dorks_live import run_dorks_live_osint

            result = await run_dorks_live_osint("example.com", max_dorks=1)

        assert len(result) == 1
        assert "site:" in result[0]["query"] or "example.com" in result[0]["query"]

    async def test_no_organic_results_shows_placeholder(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")

        mock_resp = _mock_serp_response(200, {"organic": []})
        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            from openosint.tools.search_dorks_live import run_dorks_live_osint

            result = await run_dorks_live_osint("target", max_dorks=1)

        assert len(result) == 1
        assert result[0]["results"] == []

    async def test_organic_link_field_used_as_url(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")

        mock_resp = _mock_serp_response(
            200,
            {
                "organic": [
                    {"title": "T", "link": "https://primary-link.com", "description": ""},
                ]
            },
        )
        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            from openosint.tools.search_dorks_live import run_dorks_live_osint

            result = await run_dorks_live_osint("target", max_dorks=1)

        assert len(result) == 1
        assert result[0]["results"][0]["url"] == "https://primary-link.com"

    async def test_request_uses_format_raw_not_json(self, monkeypatch):
        """Verify the outbound request body uses format=raw to prevent envelope wrapping."""
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")

        mock_resp = _mock_serp_response(200, {"organic": []})
        with patch(
            "openosint.tools.search_dorks_live.requests.post", return_value=mock_resp
        ) as mock_post:
            from openosint.tools.search_dorks_live import run_dorks_live_osint

            await run_dorks_live_osint("target", max_dorks=1)

        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs.get("json", {})
        assert payload.get("format") == "raw", "Must use format=raw to avoid double-parse"
        assert payload.get("data_format") == "parsed_light"

    async def test_http_401_returns_auth_error(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "bad-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")

        mock_resp = _mock_serp_response(401)
        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            from openosint.tools.search_dorks_live import run_dorks_live_osint

            result = await run_dorks_live_osint("target", max_dorks=1)

        assert "invalid api key" in result.lower() or "error" in result.lower()

    async def test_http_429_returns_rate_limit_error(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")

        mock_resp = _mock_serp_response(429)
        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            from openosint.tools.search_dorks_live import run_dorks_live_osint

            result = await run_dorks_live_osint("target", max_dorks=1)

        assert "rate limit" in result.lower() or "error" in result.lower()

    async def test_all_requests_fail_returns_scan_error(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")

        mock_resp = _mock_serp_response(500)
        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            from openosint.tools.search_dorks_live import run_dorks_live_osint

            result = await run_dorks_live_osint("target", max_dorks=2)

        assert "Scan error" in result

    async def test_network_exception_handled_gracefully(self, monkeypatch):
        import requests as _requests

        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")

        with patch(
            "openosint.tools.search_dorks_live.requests.post",
            side_effect=_requests.RequestException("connection refused"),
        ):
            from openosint.tools.search_dorks_live import run_dorks_live_osint

            result = await run_dorks_live_osint("target", max_dorks=1)

        assert isinstance(result, str)
        assert "error" in result.lower()


# ---------------------------------------------------------------------------
# scrape_url
# ---------------------------------------------------------------------------


class TestScrapeUrl:
    async def test_missing_api_key_returns_error_string(self, monkeypatch):
        monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
        monkeypatch.delenv("BRIGHTDATA_UNLOCKER_ZONE", raising=False)
        from openosint.tools.scrape_url import run_scrape_url_osint

        result = await run_scrape_url_osint("https://example.com")
        assert "BRIGHTDATA_API_KEY" in result
        assert "5,000" in result
        assert "get.brightdata.com" in result

    async def test_missing_zone_returns_error_string(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.delenv("BRIGHTDATA_UNLOCKER_ZONE", raising=False)
        from openosint.tools.scrape_url import run_scrape_url_osint

        result = await run_scrape_url_osint("https://example.com")
        assert "BRIGHTDATA_UNLOCKER_ZONE" in result
        assert "get.brightdata.com" in result

    async def test_does_not_raise_on_missing_key(self, monkeypatch):
        monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
        monkeypatch.delenv("BRIGHTDATA_UNLOCKER_ZONE", raising=False)
        from openosint.tools.scrape_url import run_scrape_url_osint

        result = await run_scrape_url_osint("https://example.com")
        assert isinstance(result, str)

    async def test_invalid_url_returns_error_string(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "web_unlocker1")
        from openosint.tools.scrape_url import run_scrape_url_osint

        result = await run_scrape_url_osint("not-a-url")
        assert "Invalid URL" in result

    async def test_success_returns_markdown_content(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "web_unlocker1")

        # format="raw": response.text IS the markdown string — no JSON envelope
        markdown_body = "# Example Domain\n\nThis domain is for illustrative examples."
        mock_resp = _mock_unlocker_response(200, text=markdown_body)

        with patch("openosint.tools.scrape_url.requests.post", return_value=mock_resp):
            from openosint.tools.scrape_url import run_scrape_url_osint

            result = await run_scrape_url_osint("https://example.com")

        assert "# Example Domain" in result
        assert "[Web Unlocker] URL: https://example.com" in result
        # No Remote status line — format=raw returns no envelope
        assert "Remote status" not in result

    async def test_success_result_contains_url_header(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "web_unlocker1")

        mock_resp = _mock_unlocker_response(200, text="some markdown content")
        with patch("openosint.tools.scrape_url.requests.post", return_value=mock_resp):
            from openosint.tools.scrape_url import run_scrape_url_osint

            result = await run_scrape_url_osint("https://example.com")

        assert "[Web Unlocker] URL: https://example.com" in result
        assert "some markdown content" in result

    async def test_empty_body_shows_placeholder(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "web_unlocker1")

        mock_resp = _mock_unlocker_response(200, text="")
        with patch("openosint.tools.scrape_url.requests.post", return_value=mock_resp):
            from openosint.tools.scrape_url import run_scrape_url_osint

            result = await run_scrape_url_osint("https://example.com")

        assert "empty response body" in result

    async def test_request_uses_format_raw_not_json(self, monkeypatch):
        """Verify the outbound request body uses format=raw to avoid JSON envelope parsing."""
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "web_unlocker1")

        mock_resp = _mock_unlocker_response(200, text="content")
        with patch("openosint.tools.scrape_url.requests.post", return_value=mock_resp) as mock_post:
            from openosint.tools.scrape_url import run_scrape_url_osint

            await run_scrape_url_osint("https://example.com")

        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs.get("json", {})
        assert payload.get("format") == "raw", "Must use format=raw to avoid envelope parsing"
        assert payload.get("data_format") == "markdown"

    async def test_http_401_returns_auth_error(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "bad-key")
        monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "web_unlocker1")

        mock_resp = _mock_unlocker_response(401)
        with patch("openosint.tools.scrape_url.requests.post", return_value=mock_resp):
            from openosint.tools.scrape_url import run_scrape_url_osint

            result = await run_scrape_url_osint("https://example.com")

        assert "invalid api key" in result.lower() or "scan error" in result.lower()

    async def test_http_403_returns_forbidden_error(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "web_unlocker1")

        mock_resp = _mock_unlocker_response(403)
        with patch("openosint.tools.scrape_url.requests.post", return_value=mock_resp):
            from openosint.tools.scrape_url import run_scrape_url_osint

            result = await run_scrape_url_osint("https://example.com")

        assert "forbidden" in result.lower() or "scan error" in result.lower()

    async def test_http_429_returns_rate_limit_error(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "web_unlocker1")

        mock_resp = _mock_unlocker_response(429)
        with patch("openosint.tools.scrape_url.requests.post", return_value=mock_resp):
            from openosint.tools.scrape_url import run_scrape_url_osint

            result = await run_scrape_url_osint("https://example.com")

        assert "rate limit" in result.lower() or "scan error" in result.lower()

    async def test_http_500_returns_error(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "web_unlocker1")

        mock_resp = _mock_unlocker_response(500)
        with patch("openosint.tools.scrape_url.requests.post", return_value=mock_resp):
            from openosint.tools.scrape_url import run_scrape_url_osint

            result = await run_scrape_url_osint("https://example.com")

        assert "error" in result.lower()

    async def test_network_exception_handled_gracefully(self, monkeypatch):
        import requests as _requests

        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "web_unlocker1")

        with patch(
            "openosint.tools.scrape_url.requests.post",
            side_effect=_requests.RequestException("timeout"),
        ):
            from openosint.tools.scrape_url import run_scrape_url_osint

            result = await run_scrape_url_osint("https://example.com")

        assert isinstance(result, str)
        assert "error" in result.lower()
