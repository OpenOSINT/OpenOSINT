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

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_serp_response(
    status_code: int, json_body: dict | None = None, headers: dict | None = None
) -> MagicMock:
    """Mock for SERP calls: response.json() returns parsed SERP data.

    Bright Data returns HTTP 200 at the API level with the real outcome in
    x-brd-* response headers, so ``headers`` defaults to an empty dict rather
    than an unconfigured MagicMock (which would look truthy to ``.get()``).
    """
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.headers = headers if headers is not None else {}
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

        assert "John Doe LinkedIn" in result
        assert "linkedin.com/in/johndoe" in result
        assert "Software engineer" in result

    async def test_success_result_contains_dork_header(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")

        mock_resp = _mock_serp_response(200, {"organic": []})
        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            from openosint.tools.search_dorks_live import run_dorks_live_osint

            result = await run_dorks_live_osint("example.com", max_dorks=1)

        assert "[+] Dork:" in result

    async def test_no_organic_results_shows_placeholder(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")

        mock_resp = _mock_serp_response(200, {"organic": []})
        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            from openosint.tools.search_dorks_live import run_dorks_live_osint

            result = await run_dorks_live_osint("target", max_dorks=1)

        assert "no organic results" in result

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

        assert "primary-link.com" in result

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

    async def test_one_dork_failing_does_not_stop_others(self, monkeypatch):
        """A JSONDecodeError-style failure on one dork must not abort the rest."""
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")

        bad_resp = _mock_serp_response(200)
        bad_resp.text = ""  # empty body -> SerpFetchError
        good_resp = _mock_serp_response(200, {"organic": []})
        good_resp.text = '{"organic": []}'

        with patch(
            "openosint.tools.search_dorks_live.requests.post",
            side_effect=[bad_resp, good_resp],
        ):
            from openosint.tools.search_dorks_live import run_dorks_live_osint

            result = await run_dorks_live_osint("target", max_dorks=2)

        assert "(error:" in result
        assert "(no organic results)" in result

    async def test_x_twitter_dork_string(self):
        from openosint.tools.generate_dorks import _DORK_TEMPLATES

        assert '("{target}") (site:x.com OR site:twitter.com)' in _DORK_TEMPLATES
        assert '"{target}" site:twitter.com' not in _DORK_TEMPLATES
        assert '"{target}" site:x.com OR site:twitter.com' not in _DORK_TEMPLATES

    async def test_x_twitter_dork_built_string_is_grouped(self):
        from openosint.tools.generate_dorks import _DORK_TEMPLATES

        template = next(t for t in _DORK_TEMPLATES if "x.com" in t and "twitter.com" in t)
        built = template.format(target="openosint.tech")
        assert built == '("openosint.tech") (site:x.com OR site:twitter.com)'

    async def test_all_dorks_failed_summarizes_distinct_error_codes(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")

        resp_502 = _mock_serp_response(
            200,
            headers={
                "x-brd-status-code": "502",
                "x-brd-error-code": "expect_body",
                "x-brd-error": "response body was rejected",
            },
        )
        resp_502.text = ""
        resp_429 = _mock_serp_response(
            200,
            headers={
                "x-brd-status-code": "429",
                "x-brd-error-code": "failed_query_rejected",
                "x-brd-error": "same query blocked",
            },
        )
        resp_429.text = ""

        with patch(
            "openosint.tools.search_dorks_live.requests.post",
            side_effect=[resp_502, resp_502, resp_502, resp_429, resp_429],
        ):
            from openosint.tools.search_dorks_live import run_dorks_live_osint

            result = await run_dorks_live_osint("target", max_dorks=5)

        assert "all 5 dorks failed" in result
        assert "3x 502 expect_body" in result
        assert "2x 429 failed_query_rejected" in result
        assert "BRIGHTDATA_API_KEY" not in result


class TestCleanLink:
    def test_clean_absolute_url_returned_as_is(self):
        from openosint.tools.search_dorks_live import _clean_link

        assert _clean_link({"link": "https://example.com/page"}) == "https://example.com/page"

    def test_google_url_redirect_with_absolute_q_param_unwrapped(self):
        from openosint.tools.search_dorks_live import _clean_link

        item = {"link": "/url?q=https://example.com/page&sa=U"}
        assert _clean_link(item) == "https://example.com/page"

    def test_opaque_goto_redirect_returns_none(self):
        from openosint.tools.search_dorks_live import _clean_link

        item = {"link": "/goto?url=CAESdgHrOzAVwmzu3csuqwCiDN3m8jAH92tze2GTyVr0E4Rn"}
        assert _clean_link(item) is None

    def test_url_with_trailing_snippet_text_keeps_first_token(self):
        from openosint.tools.search_dorks_live import _clean_link

        item = {"link": "https://lnkd.in/g8BV_Fwz — openosint.tech #OSINT #infosec"}
        assert _clean_link(item) == "https://lnkd.in/g8BV_Fwz"

    def test_empty_field_returns_none(self):
        from openosint.tools.search_dorks_live import _clean_link

        assert _clean_link({"link": ""}) is None

    def test_missing_field_returns_none(self):
        from openosint.tools.search_dorks_live import _clean_link

        assert _clean_link({}) is None


class TestExtractOrganic:
    def test_unresolvable_link_kept_with_url_none(self):
        from openosint.tools.search_dorks_live import _extract_organic

        data = {
            "organic": [
                {"title": "Unresolvable", "link": "/goto?url=CAESdgHrOzAV", "description": "x"},
            ]
        }
        results = _extract_organic(data)

        assert len(results) == 1
        assert results[0]["url"] is None
        assert results[0]["title"] == "Unresolvable"


class TestFetchSerp:
    def test_empty_200_body_raises_serp_fetch_error(self):
        from openosint.tools.search_dorks_live import SerpFetchError, _fetch_serp

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        mock_resp.headers = {"content-type": "application/json"}

        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            with pytest.raises(SerpFetchError) as exc_info:
                _fetch_serp("https://www.google.com/search?q=x", "test-key", "serp_api1", 30)

        message = str(exc_info.value)
        assert "200" in message
        assert "application/json" in message

    def test_502_raises_serp_fetch_error(self):
        from openosint.tools.search_dorks_live import SerpFetchError, _fetch_serp

        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_resp.text = "Bad Gateway"
        mock_resp.headers = {"content-type": "text/plain"}

        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            with pytest.raises(SerpFetchError) as exc_info:
                _fetch_serp("https://www.google.com/search?q=x", "test-key", "serp_api1", 30)

        assert "502" in str(exc_info.value)

    def test_html_body_raises_serp_fetch_error(self):
        from openosint.tools.search_dorks_live import SerpFetchError, _fetch_serp

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>proxy auth required</body></html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")

        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            with pytest.raises(SerpFetchError) as exc_info:
                _fetch_serp("https://www.google.com/search?q=x", "test-key", "serp_api1", 30)

        message = str(exc_info.value)
        assert "text/html" in message

    def test_does_not_bypass_ambient_proxy_env_vars(self, monkeypatch):
        """Users behind a mandatory corporate proxy must not be silently bypassed."""
        from openosint.tools.search_dorks_live import _fetch_serp

        mock_resp = _mock_serp_response(200, {"organic": []})
        mock_resp.text = '{"organic": []}'

        with patch(
            "openosint.tools.search_dorks_live.requests.post", return_value=mock_resp
        ) as mock_post:
            _fetch_serp("https://www.google.com/search?q=x", "test-key", "serp_api1", 30)

        assert "proxies" not in mock_post.call_args.kwargs

    def test_502_expect_body_uses_brd_headers(self):
        from openosint.tools.search_dorks_live import SerpFetchError, _fetch_serp

        mock_resp = _mock_serp_response(
            200,
            headers={
                "x-brd-status-code": "502",
                "x-brd-error-code": "expect_body",
                "x-brd-error": "response body was rejected",
            },
        )
        mock_resp.text = ""

        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            with pytest.raises(SerpFetchError) as exc_info:
                _fetch_serp("https://www.google.com/search?q=x", "test-key", "serp_api1", 30)

        message = str(exc_info.value)
        assert message == "Bright Data 502 expect_body: response body was rejected"
        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "expect_body"

    def test_502_captcha_adds_verification_hint(self):
        from openosint.tools.search_dorks_live import SerpFetchError, _fetch_serp

        mock_resp = _mock_serp_response(
            200,
            headers={
                "x-brd-status-code": "502",
                "x-brd-error-code": "captcha",
                "x-brd-error": "redirect location was rejected",
            },
        )
        mock_resp.text = ""

        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            with pytest.raises(SerpFetchError) as exc_info:
                _fetch_serp("https://www.google.com/search?q=x", "test-key", "serp_api1", 30)

        message = str(exc_info.value)
        assert "captcha" in message
        assert "search engine returned a verification page; not billed" in message

    def test_429_failed_query_rejected_no_retry(self):
        """A rejected query is never retried — requests.post is called exactly once."""
        from openosint.tools.search_dorks_live import SerpFetchError, _fetch_serp

        mock_resp = _mock_serp_response(
            200,
            headers={
                "x-brd-status-code": "429",
                "x-brd-error-code": "failed_query_rejected",
            },
        )
        mock_resp.text = ""

        with patch(
            "openosint.tools.search_dorks_live.requests.post", return_value=mock_resp
        ) as mock_post:
            with pytest.raises(SerpFetchError) as exc_info:
                _fetch_serp("https://www.google.com/search?q=x", "test-key", "serp_api1", 30)

        assert mock_post.call_count == 1
        message = str(exc_info.value)
        assert "failed_query_rejected" in message
        assert "retry after 15 seconds" in message

    def test_wrong_api_status_400(self):
        from openosint.tools.search_dorks_live import SerpFetchError, _fetch_serp

        mock_resp = _mock_serp_response(
            200,
            headers={"x-brd-status-code": "400", "x-brd-error-code": "wrong_api"},
        )
        mock_resp.text = ""

        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            with pytest.raises(SerpFetchError) as exc_info:
                _fetch_serp("https://www.google.com/search?q=x", "test-key", "serp_api1", 30)

        assert "wrong_api" in str(exc_info.value)

    def test_proxy_layer_err_code_fallback(self):
        """Proxy-layer failures use x-brd-err-code/x-brd-err-msg, not x-brd-error-code/-error."""
        from openosint.tools.search_dorks_live import SerpFetchError, _fetch_serp

        mock_resp = _mock_serp_response(
            200,
            headers={
                "x-brd-status-code": "502",
                "x-brd-err-code": "proxy_error",
                "x-brd-err-msg": "no peers available",
            },
        )
        mock_resp.text = ""

        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            with pytest.raises(SerpFetchError) as exc_info:
                _fetch_serp("https://www.google.com/search?q=x", "test-key", "serp_api1", 30)

        message = str(exc_info.value)
        assert "proxy_error" in message
        assert "no peers available" in message

    def test_empty_body_with_no_brd_headers_falls_back(self):
        from openosint.tools.search_dorks_live import SerpFetchError, _fetch_serp

        mock_resp = _mock_serp_response(200)
        mock_resp.text = ""

        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            with pytest.raises(SerpFetchError) as exc_info:
                _fetch_serp("https://www.google.com/search?q=x", "test-key", "serp_api1", 30)

        assert "empty response body" in str(exc_info.value)

    def test_401_token_expired_message(self):
        from openosint.tools.search_dorks_live import SerpFetchError, _fetch_serp

        mock_resp = _mock_serp_response(401)
        mock_resp.text = '{"error": "Token expired"}'

        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            with pytest.raises(SerpFetchError) as exc_info:
                _fetch_serp("https://www.google.com/search?q=x", "test-key", "serp_api1", 30)

        message = str(exc_info.value)
        assert "Token expired" in message
        assert "renew it in the Bright Data dashboard" in message

    def test_401_body_included_and_key_redacted(self):
        from openosint.tools.search_dorks_live import SerpFetchError, _fetch_serp

        mock_resp = _mock_serp_response(401)
        mock_resp.text = '{"error": "invalid key test-key"}'

        with patch("openosint.tools.search_dorks_live.requests.post", return_value=mock_resp):
            with pytest.raises(SerpFetchError) as exc_info:
                _fetch_serp("https://www.google.com/search?q=x", "test-key", "serp_api1", 30)

        message = str(exc_info.value)
        assert "test-key" not in message
        assert "***REDACTED***" in message

    def test_build_google_url_contains_hl_and_gl(self):
        from openosint.tools.search_dorks_live import _build_google_url

        url = _build_google_url('"openosint.tech"')
        assert "hl=en" in url
        assert "gl=us" in url
        assert url.endswith("&hl=en&gl=us")


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
