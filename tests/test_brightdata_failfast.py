"""The three Bright Data tools stop at the first account-level failure and say why. Mocked HTTP only."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openosint.brightdata_response import BILLING_URL, TOKEN_URL


def _resp(status=200, text="", headers=None, json_body=None):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.headers = headers if headers is not None else {}
    resp.json.return_value = json_body or {}
    return resp


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "fake-token")
    monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")
    monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "web_unlocker1")


class TestDorksFailFast:
    async def test_invalid_token_sends_one_request_and_reports_the_cause(self):
        from openosint.tools.search_dorks_live import run_dorks_live_osint

        with patch(
            "openosint.tools.search_dorks_live.requests.post",
            return_value=_resp(401, "Invalid token"),
        ) as post:
            result = await run_dorks_live_osint("example.com", max_dorks=5)

        assert post.call_count == 1
        assert result.startswith("Scan error:") and TOKEN_URL in result and "5x" not in result
        assert "get.brightdata.com" not in result

    async def test_a_bright_data_outage_is_not_blamed_on_the_key(self):
        from openosint.tools.search_dorks_live import run_dorks_live_osint

        with patch(
            "openosint.tools.search_dorks_live.requests.post",
            return_value=_resp(502, "Bad Gateway"),
        ) as post:
            result = await run_dorks_live_osint("example.com", max_dorks=5)

        assert post.call_count == 1
        assert "Bright Data-side" in result and "contact Bright Data support" in result
        assert "BRIGHTDATA_API_KEY" not in result and TOKEN_URL not in result

    async def test_wrong_zone_stops_and_names_the_variable(self):
        from openosint.tools.search_dorks_live import run_dorks_live_osint

        with patch(
            "openosint.tools.search_dorks_live.requests.post",
            return_value=_resp(400, 'zone "serp_api1" not found'),
        ) as post:
            result = await run_dorks_live_osint("example.com", max_dorks=5)

        assert post.call_count == 1 and "BRIGHTDATA_SERP_ZONE" in result and "'serp_api1'" in result

    async def test_usage_limit_hint_points_at_billing_without_claiming_certainty(self):
        from openosint.tools.search_dorks_live import run_dorks_live_osint

        limited = _resp(200, "", {"x-brd-err-code": "client_10100"})
        with patch("openosint.tools.search_dorks_live.requests.post", return_value=limited) as post:
            result = await run_dorks_live_osint("example.com", max_dorks=5)

        assert post.call_count == 1 and "may mean" in result and BILLING_URL in result

    async def test_results_gathered_before_a_stop_are_kept(self):
        from openosint.tools.search_dorks_live import run_dorks_live_osint

        good = _resp(
            200,
            '{"organic": []}',
            json_body={"organic": [{"title": "T", "link": "https://a.example/x"}]},
        )
        bad = _resp(502, "Bad Gateway")
        with patch(
            "openosint.tools.search_dorks_live.requests.post", side_effect=[good, bad]
        ) as post:
            result = await run_dorks_live_osint("example.com", max_dorks=5)

        assert post.call_count == 2
        assert (
            "https://a.example/x" in result
            and "stopped" in result.lower()
            and "Bright Data-side" in result
        )

    async def test_per_query_target_failures_still_continue(self):
        from openosint.tools.search_dorks_live import run_dorks_live_osint

        blocked = _resp(200, "", {"x-brd-status-code": "502", "x-brd-error-code": "reject_block"})
        with patch("openosint.tools.search_dorks_live.requests.post", return_value=blocked) as post:
            result = await run_dorks_live_osint("example.com", max_dorks=3)

        assert post.call_count == 3 and "all 3 dorks failed" in result


class TestFootprintFailFast:
    async def test_invalid_token_sends_one_request_and_reports_the_cause(self):
        from openosint.tools.search_footprint import run_footprint_osint

        with patch(
            "openosint.tools.search_footprint.requests.post",
            return_value=_resp(401, "Invalid token"),
        ) as post:
            result = await run_footprint_osint("john doe", max_queries=3)

        assert post.call_count == 1
        assert (
            result.startswith("Scan error:") and TOKEN_URL in result and "get.brightdata.com" not in result
        )

    async def test_outage_is_reported_as_bright_datas(self):
        from openosint.tools.search_footprint import run_footprint_osint

        with patch(
            "openosint.tools.search_footprint.requests.post", return_value=_resp(504, "")
        ) as post:
            result = await run_footprint_osint("john doe", max_queries=3)

        assert (
            post.call_count == 1
            and "Bright Data-side" in result
            and "BRIGHTDATA_API_KEY" not in result
        )

    async def test_a_429_does_not_stop_the_other_queries(self):
        from openosint.tools.search_footprint import run_footprint_osint

        with patch(
            "openosint.tools.search_footprint.requests.post", return_value=_resp(429, "")
        ) as post:
            result = await run_footprint_osint("john doe", max_queries=2)

        assert post.call_count == 2 and "Scan error" in result


class TestScrapeUrlReadsTheOutcomeHeaders:
    async def test_a_blocked_target_is_an_error_not_content(self):
        from openosint.tools.scrape_url import run_scrape_url_osint

        blocked = _resp(
            200,
            "<html>captcha</html>",
            {
                "x-brd-status-code": "502",
                "x-brd-error-code": "reject_block",
                "x-brd-error": "captcha or protection page found",
            },
        )
        with patch("openosint.tools.scrape_url.requests.post", return_value=blocked):
            result = await run_scrape_url_osint("https://example.com")

        assert (
            result.startswith("Scan error:")
            and "blocked" in result.lower()
            and "captcha</html>" not in result
        )

    @pytest.mark.parametrize("status", [401, 404, 410, 429, 500, 503])
    async def test_the_targets_own_status_is_a_finding_not_a_tool_failure(self, status):
        """A 404/410 is itself an OSINT result (deleted profile, removed page): keep the status and the body."""
        from openosint.tools.scrape_url import run_scrape_url_osint

        answered = _resp(200, "Profile removed by the user", {"x-brd-status-code": str(status)})
        with patch("openosint.tools.scrape_url.requests.post", return_value=answered):
            result = await run_scrape_url_osint("https://example.com/missing")

        assert not result.startswith("Scan error")
        assert f"[Target returned HTTP {status}]" in result
        assert "Profile removed by the user" in result
        assert "[Web Unlocker] URL: https://example.com/missing" in result

    async def test_a_target_status_with_an_empty_body_still_reports_the_status(self):
        from openosint.tools.scrape_url import run_scrape_url_osint

        gone = _resp(200, "", {"x-brd-status-code": "410"})
        with patch("openosint.tools.scrape_url.requests.post", return_value=gone):
            result = await run_scrape_url_osint("https://example.com/gone")

        assert "[Target returned HTTP 410]" in result and "(empty response body)" in result

    async def test_an_anti_bot_page_is_still_an_error_even_with_a_blocking_status(self):
        from openosint.tools.scrape_url import run_scrape_url_osint

        for code in ("reject_block", "http_status"):
            blocked = _resp(
                200, "<html>blocked</html>", {"x-brd-status-code": "502", "x-brd-error-code": code}
            )
            with patch("openosint.tools.scrape_url.requests.post", return_value=blocked):
                result = await run_scrape_url_osint("https://example.com")

            assert result.startswith("Scan error:") and "<html>blocked</html>" not in result

    async def test_serp_tools_still_treat_a_non_200_from_google_as_failure(self):
        from openosint.tools.search_dorks_live import run_dorks_live_osint

        odd = _resp(200, "", {"x-brd-status-code": "404"})
        with patch("openosint.tools.search_dorks_live.requests.post", return_value=odd):
            result = await run_dorks_live_osint("example.com", max_dorks=1)

        assert "Scan error" in result

    async def test_success_with_a_brd_200_still_returns_the_page(self):
        from openosint.tools.scrape_url import run_scrape_url_osint

        ok = _resp(200, "# Example Domain", {"x-brd-status-code": "200"})
        with patch("openosint.tools.scrape_url.requests.post", return_value=ok):
            result = await run_scrape_url_osint("https://example.com")

        assert "# Example Domain" in result and "[Web Unlocker] URL: https://example.com" in result

    async def test_wrong_zone_names_the_unlocker_variable(self):
        from openosint.tools.scrape_url import run_scrape_url_osint

        with patch(
            "openosint.tools.scrape_url.requests.post",
            return_value=_resp(400, 'zone "web_unlocker1" not found'),
        ):
            result = await run_scrape_url_osint("https://example.com")

        assert "BRIGHTDATA_UNLOCKER_ZONE" in result

    async def test_invalid_token_has_no_referral_link(self):
        from openosint.tools.scrape_url import run_scrape_url_osint

        with patch(
            "openosint.tools.scrape_url.requests.post", return_value=_resp(401, "Invalid token")
        ):
            result = await run_scrape_url_osint("https://example.com")

        assert TOKEN_URL in result and "get.brightdata.com" not in result and "commission" not in result
