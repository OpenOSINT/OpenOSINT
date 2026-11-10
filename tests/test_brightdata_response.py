"""Classifying api.brightdata.com/request responses. Fake responses only, no network, no real key."""

from __future__ import annotations

import pytest

from openosint.brightdata_response import (
    BILLING_URL,
    TOKEN_URL,
    BrightDataError,
    Kind,
    classify,
)

SECRET = "sekret-token-123"


class Resp:
    def __init__(self, status=200, text="", headers=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {}


def _classify(resp, **kw):
    kw.setdefault("api_key", SECRET)
    kw.setdefault("zone", "serp_api1")
    kw.setdefault("zone_env", "BRIGHTDATA_SERP_ZONE")
    kw.setdefault("product", "SERP API")
    return classify(resp, **kw)


class TestOk:
    @pytest.mark.parametrize(
        "headers", [{}, {"x-brd-status-code": "200"}, {"x-brd-status-code": "204"}]
    )
    def test_a_good_response_is_not_an_error(self, headers):
        assert _classify(Resp(200, "ok", headers)) is None

    def test_an_empty_200_without_brd_headers_is_left_to_the_tool(self):
        assert _classify(Resp(200, "")) is None


class TestTokenRejected:
    def test_401_names_the_token_page_and_stops_the_batch(self):
        err = _classify(Resp(401, "Invalid token"))

        assert isinstance(err, BrightDataError)
        assert err.kind is Kind.TOKEN_REJECTED and err.stop_batch is True and err.status_code == 401
        assert TOKEN_URL in str(err) and "Invalid token" in str(err)

    def test_no_referral_link_on_an_existing_users_error(self):
        message = str(_classify(Resp(401, "Auth method is not supported")))

        assert (
            "get.brightdata.com" not in message
            and "get.brightdata.com" not in message
            and "commission" not in message
        )

    def test_the_key_is_redacted_from_the_body(self):
        message = str(_classify(Resp(401, f"bad {SECRET}")))

        assert SECRET not in message and "***REDACTED***" in message

    def test_an_expired_token_says_to_renew_it(self):
        message = str(_classify(Resp(401, '{"error": "Token expired"}')))

        assert "Token expired" in message and "renew it in the Bright Data dashboard" in message


class TestZone:
    def test_unknown_zone_names_the_zone_and_the_variable(self):
        err = _classify(Resp(400, 'zone "my_zone" not found'), zone="my_zone")

        assert err.kind is Kind.ZONE_NOT_FOUND and err.stop_batch is True
        assert "'my_zone'" in str(err) and "BRIGHTDATA_SERP_ZONE" in str(err)

    def test_other_400s_do_not_stop_the_batch(self):
        err = _classify(
            Resp(400, '{"error":"Request validation failed","error_code":"validation"}')
        )

        assert err.kind is Kind.REQUEST_REJECTED and err.stop_batch is False
        assert "validation" in str(err)


class TestCreditsHint:
    @pytest.mark.parametrize("status", [200, 402, 403, 429])
    def test_client_10100_is_only_ever_a_hint(self, status):
        err = _classify(Resp(status, "", {"x-brd-err-code": "client_10100"}))

        assert err.kind is Kind.CREDITS_HINT and err.stop_batch is True
        message = str(err)
        assert "may mean" in message and "free credits" in message and BILLING_URL in message
        assert "client_10100" in message
        assert "are used up" not in message.replace("may mean your free credits are used up", "")

    def test_it_never_blames_the_key(self):
        message = str(_classify(Resp(200, "", {"x-brd-err-code": "client_10100"})))

        assert "token" not in message.lower() and "BRIGHTDATA_API_KEY" not in message


class TestRateLimit:
    def test_429_is_retryable_and_mentions_the_documented_unfunded_limit(self):
        err = _classify(Resp(429, ""))

        assert err.kind is Kind.RATE_LIMITED and err.stop_batch is False
        assert "1,000 requests/minute" in str(err) and BILLING_URL in str(err)


class TestBrightDataSideErrors:
    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_5xx_from_the_api_is_never_blamed_on_the_key(self, status):
        err = _classify(Resp(status, "<html>502 Bad Gateway</html>"))
        message = str(err)

        assert (
            err.kind is Kind.SERVICE_ERROR and err.stop_batch is True and err.status_code == status
        )
        assert f"HTTP {status}" in message
        assert "Bright Data-side" in message and "not a problem with your key" in message
        assert "retry in a few minutes" in message.lower()
        assert "contact Bright Data support" in message
        assert "github.com" not in message and "http" not in message  # no link that can go stale
        assert TOKEN_URL not in message and "BRIGHTDATA_API_KEY" not in message


class TestStatusPageConstant:
    def test_a_status_page_is_added_to_the_outage_message_only_once_one_is_configured(
        self, monkeypatch
    ):
        from openosint import brightdata_response

        assert brightdata_response.STATUS_PAGE_URL == ""
        monkeypatch.setattr(brightdata_response, "STATUS_PAGE_URL", "https://status.example.test")

        assert "Status page: https://status.example.test" in str(_classify(Resp(503, "")))


class TestTargetOutcomes:
    def test_captcha_or_protection_page_is_a_target_block(self):
        err = _classify(
            Resp(
                200,
                "",
                {
                    "x-brd-status-code": "502",
                    "x-brd-error-code": "reject_block",
                    "x-brd-error": "captcha or protection page found",
                },
            ),
            product="Web Unlocker",
        )

        assert (
            err.kind is Kind.TARGET_BLOCKED
            and err.stop_batch is False
            and err.error_code == "reject_block"
        )
        assert "blocked" in str(err).lower() and "retry" in str(err).lower()

    def test_the_targets_own_403_is_reported_as_the_targets(self):
        err = _classify(Resp(200, "<html>denied</html>", {"x-brd-status-code": "403"}))

        assert err.kind is Kind.TARGET_STATUS and err.status_code == 403
        assert "target" in str(err).lower()

    def test_existing_x_brd_message_formats_are_unchanged(self):
        err = _classify(
            Resp(
                200,
                "",
                {
                    "x-brd-status-code": "502",
                    "x-brd-error-code": "expect_body",
                    "x-brd-error": "response body was rejected",
                },
            )
        )

        assert str(err) == "Bright Data 502 expect_body: response body was rejected"

    def test_unexpected_status_keeps_a_body_preview(self):
        err = _classify(Resp(418, f"teapot {SECRET}"))

        assert (
            err.kind is Kind.UNEXPECTED
            and "418" in str(err)
            and "teapot" in str(err)
            and SECRET not in str(err)
        )


class TestForbidden:
    def test_403_is_a_policy_or_permission_refusal_not_a_bad_key(self):
        err = _classify(Resp(403, "Forbidden: You tried to target x but got blocked"))

        assert err.kind is Kind.FORBIDDEN and err.stop_batch is False
        assert "403" in str(err) and "permission" in str(err).lower()
        assert "token" not in str(err).lower()
