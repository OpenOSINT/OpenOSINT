# tests/test_tools.py
"""
Tests for individual tool modules: binary-missing, API-key-missing,
input detection helpers, generate_dorks output, and session history.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# generate_dorks — pure computation, no external deps
# ---------------------------------------------------------------------------


class TestGenerateDorks:
    async def test_returns_non_empty_string(self):
        from openosint.tools.generate_dorks import run_dork_osint

        result = await run_dork_osint("test@example.com")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_contains_google_search_url(self):
        from openosint.tools.generate_dorks import run_dork_osint

        result = await run_dork_osint("johndoe")
        assert "google.com/search" in result

    async def test_target_appears_in_output(self):
        from openosint.tools.generate_dorks import run_dork_osint

        result = await run_dork_osint("uniquetarget99")
        assert "uniquetarget99" in result

    async def test_produces_multiple_dork_lines(self):
        from openosint.tools.generate_dorks import run_dork_osint

        result = await run_dork_osint("example.com")
        assert result.count("[+]") >= 5


# ---------------------------------------------------------------------------
# search_email — binary missing
# ---------------------------------------------------------------------------


class TestSearchEmailMissingBinary:
    async def test_returns_string_when_holehe_absent(self, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "which", lambda *_, **__: None)
        from openosint.tools.search_email import run_email_osint

        result = await run_email_osint("test@example.com")
        assert isinstance(result, str)

    async def test_error_mentions_holehe(self, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "which", lambda *_, **__: None)
        from openosint.tools.search_email import run_email_osint

        result = await run_email_osint("test@example.com")
        assert "holehe" in result.lower() or "scan error" in result.lower()

    async def test_does_not_raise(self, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "which", lambda *_, **__: None)
        from openosint.tools.search_email import run_email_osint

        try:
            await run_email_osint("test@example.com")
        except Exception as exc:
            pytest.fail(f"run_email_osint raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# search_username — binary missing
# ---------------------------------------------------------------------------


class TestSearchUsernameMissingBinary:
    async def test_returns_string_when_sherlock_absent(self, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "which", lambda *_, **__: None)
        from openosint.tools.search_username import run_username_osint

        result = await run_username_osint("johndoe")
        assert isinstance(result, str)

    async def test_error_mentions_sherlock(self, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "which", lambda *_, **__: None)
        from openosint.tools.search_username import run_username_osint

        result = await run_username_osint("johndoe")
        assert "sherlock" in result.lower() or "scan error" in result.lower()

    async def test_does_not_raise(self, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "which", lambda *_, **__: None)
        from openosint.tools.search_username import run_username_osint

        try:
            await run_username_osint("johndoe")
        except Exception as exc:
            pytest.fail(f"run_username_osint raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# search_domain — binary missing
# ---------------------------------------------------------------------------


class TestSearchDomainMissingBinary:
    async def test_returns_string_when_sublist3r_absent(self, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "which", lambda *_, **__: None)
        from openosint.tools.search_domain import run_domain_osint

        result = await run_domain_osint("example.com")
        assert isinstance(result, str)

    async def test_error_mentions_sublist3r(self, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "which", lambda *_, **__: None)
        from openosint.tools.search_domain import run_domain_osint

        result = await run_domain_osint("example.com")
        assert "sublist3r" in result.lower() or "scan error" in result.lower()

    async def test_does_not_raise(self, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "which", lambda *_, **__: None)
        from openosint.tools.search_domain import run_domain_osint

        try:
            await run_domain_osint("example.com")
        except Exception as exc:
            pytest.fail(f"run_domain_osint raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# search_phone — binary missing
# ---------------------------------------------------------------------------


class TestSearchPhoneMissingBinary:
    async def test_returns_string_when_phoneinfoga_absent(self, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "which", lambda *_, **__: None)
        from openosint.tools.search_phone import run_phone_osint

        result = await run_phone_osint("+14155552671")
        assert isinstance(result, str)

    async def test_error_mentions_phoneinfoga(self, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "which", lambda *_, **__: None)
        from openosint.tools.search_phone import run_phone_osint

        result = await run_phone_osint("+14155552671")
        assert "phoneinfoga" in result.lower() or "scan error" in result.lower()

    async def test_does_not_raise(self, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "which", lambda *_, **__: None)
        from openosint.tools.search_phone import run_phone_osint

        try:
            await run_phone_osint("+14155552671")
        except Exception as exc:
            pytest.fail(f"run_phone_osint raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# search_breach — API key missing
# ---------------------------------------------------------------------------


class TestSearchBreachMissingApiKey:
    async def test_returns_string_when_hibp_key_absent(self, monkeypatch):
        monkeypatch.delenv("HIBP_API_KEY", raising=False)
        from openosint.tools.search_breach import run_breach_osint

        result = await run_breach_osint("test@example.com")
        assert isinstance(result, str)

    async def test_error_mentions_hibp_key(self, monkeypatch):
        monkeypatch.delenv("HIBP_API_KEY", raising=False)
        from openosint.tools.search_breach import run_breach_osint

        result = await run_breach_osint("test@example.com")
        assert "HIBP_API_KEY" in result

    async def test_does_not_raise_when_key_absent(self, monkeypatch):
        monkeypatch.delenv("HIBP_API_KEY", raising=False)
        from openosint.tools.search_breach import run_breach_osint

        try:
            await run_breach_osint("test@example.com")
        except Exception as exc:
            pytest.fail(f"run_breach_osint raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# search_virustotal — API key missing + input detection
# ---------------------------------------------------------------------------


class TestSearchVirusTotalMissingApiKey:
    async def test_returns_string_when_vt_key_absent(self, monkeypatch):
        monkeypatch.delenv("VIRUSTOTAL_API_KEY", raising=False)
        from openosint.tools.search_virustotal import run_virustotal_osint

        result = await run_virustotal_osint("8.8.8.8")
        assert isinstance(result, str)

    async def test_error_mentions_virustotal_key(self, monkeypatch):
        monkeypatch.delenv("VIRUSTOTAL_API_KEY", raising=False)
        from openosint.tools.search_virustotal import run_virustotal_osint

        result = await run_virustotal_osint("example.com")
        assert "VIRUSTOTAL_API_KEY" in result

    async def test_does_not_raise_when_key_absent(self, monkeypatch):
        monkeypatch.delenv("VIRUSTOTAL_API_KEY", raising=False)
        from openosint.tools.search_virustotal import run_virustotal_osint

        try:
            await run_virustotal_osint("https://evil.example.com")
        except Exception as exc:
            pytest.fail(f"run_virustotal_osint raised unexpectedly: {exc}")


class TestVirusTotalInputDetection:
    def test_detects_ipv4(self):
        from openosint.tools.search_virustotal import _detect_input_type

        assert _detect_input_type("8.8.8.8") == "ip"
        assert _detect_input_type("192.168.1.1") == "ip"
        assert _detect_input_type("0.0.0.0") == "ip"

    def test_detects_https_url(self):
        from openosint.tools.search_virustotal import _detect_input_type

        assert _detect_input_type("https://example.com/path") == "url"

    def test_detects_http_url(self):
        from openosint.tools.search_virustotal import _detect_input_type

        assert _detect_input_type("http://evil.com/malware.exe") == "url"

    def test_detects_md5_hash(self):
        from openosint.tools.search_virustotal import _detect_input_type

        assert _detect_input_type("a" * 32) == "hash"

    def test_detects_sha1_hash(self):
        from openosint.tools.search_virustotal import _detect_input_type

        assert _detect_input_type("a" * 40) == "hash"

    def test_detects_sha256_hash(self):
        from openosint.tools.search_virustotal import _detect_input_type

        assert _detect_input_type("a" * 64) == "hash"

    def test_detects_domain(self):
        from openosint.tools.search_virustotal import _detect_input_type

        assert _detect_input_type("example.com") == "domain"
        assert _detect_input_type("evil.site.ru") == "domain"

    def test_non_ip_non_hash_non_url_is_domain(self):
        from openosint.tools.search_virustotal import _detect_input_type

        assert _detect_input_type("openosint.github.io") == "domain"


# ---------------------------------------------------------------------------
# search_ip — output formatting
# ---------------------------------------------------------------------------


class TestSearchIpFormatting:
    def test_format_bogon(self):
        from openosint.tools.search_ip import _format_ip_results

        result = _format_ip_results({"bogon": True}, "192.168.1.1")
        assert "bogon" in result.lower() or "private" in result.lower()

    def test_format_real_ip(self):
        from openosint.tools.search_ip import _format_ip_results

        data = {
            "ip": "8.8.8.8",
            "org": "AS15169 Google LLC",
            "city": "Mountain View",
            "country": "US",
        }
        result = _format_ip_results(data, "8.8.8.8")
        assert "8.8.8.8" in result
        assert "Google" in result


# ---------------------------------------------------------------------------
# search_gdelt_geo
# ---------------------------------------------------------------------------


def _gdelt_feature(lon, lat, name="Kyiv, Ukraine", count=4):
    return {
        "type": "Feature",
        "properties": {"name": name, "count": count},
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


def _gdelt_fc(features):
    return {"type": "FeatureCollection", "features": features}


class TestSearchGdeltGeoHappyPath:
    async def test_returns_summary_and_geojson_fence(self):
        from openosint.tools.search_gdelt_geo import run_gdelt_geo_osint

        fc = _gdelt_fc([_gdelt_feature(30.52, 50.45)])
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: fc

        with patch("openosint.tools.search_gdelt_geo.requests.get", return_value=mock_response):
            result = await run_gdelt_geo_osint("ukraine war", timeout_seconds=5)

        assert "Kyiv, Ukraine" in result
        assert "```geojson" in result
        assert '"type": "FeatureCollection"' in result or '"type":"FeatureCollection"' in result

    async def test_clamps_timespan_and_maxpoints(self):
        from openosint.tools.search_gdelt_geo import (
            _MAX_MAXPOINTS,
            _MAX_TIMESPAN,
            run_gdelt_geo_osint,
        )

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: _gdelt_fc([])

        with patch(
            "openosint.tools.search_gdelt_geo.requests.get", return_value=mock_response
        ) as mock_get:
            await run_gdelt_geo_osint(
                "x", timeout_seconds=5, timespan=999999, maxpoints=999999
            )

        params = mock_get.call_args.kwargs["params"]
        assert params["timespan"] == _MAX_TIMESPAN
        assert params["maxpoints"] == _MAX_MAXPOINTS


class TestSearchGdeltGeoEmptyResult:
    async def test_empty_feature_collection_returns_no_results_message(self):
        from openosint.tools.search_gdelt_geo import run_gdelt_geo_osint

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: _gdelt_fc([])

        with patch("openosint.tools.search_gdelt_geo.requests.get", return_value=mock_response):
            result = await run_gdelt_geo_osint("no such thing", timeout_seconds=5)

        assert "No geolocated coverage found" in result
        assert "```geojson" not in result


class TestSearchGdeltGeoUpstreamError:
    async def test_upstream_5xx_returns_clean_error_string(self):
        from openosint.tools.search_gdelt_geo import run_gdelt_geo_osint

        mock_response = AsyncMock()
        mock_response.status_code = 503

        with patch("openosint.tools.search_gdelt_geo.requests.get", return_value=mock_response):
            result = await run_gdelt_geo_osint("query", timeout_seconds=5)

        assert "Scan error" in result
        assert "503" in result

    async def test_network_timeout_returns_clean_error_string(self):
        import requests

        from openosint.tools.search_gdelt_geo import run_gdelt_geo_osint

        with patch(
            "openosint.tools.search_gdelt_geo.requests.get",
            side_effect=requests.Timeout("timed out"),
        ):
            result = await run_gdelt_geo_osint("query", timeout_seconds=5)

        assert "Scan error" in result
        assert "timed out" in result.lower()

    async def test_uses_short_connect_timeout_not_full_read_budget(self):
        """A single flat timeout applies to both connect and read — a host
        that hangs mid-TLS (GDELT during an outage) would otherwise block
        for the full read budget instead of failing fast."""
        from openosint.tools.search_gdelt_geo import (
            _CONNECT_TIMEOUT_SECONDS,
            run_gdelt_geo_osint,
        )

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: _gdelt_fc([])

        with patch(
            "openosint.tools.search_gdelt_geo.requests.get", return_value=mock_response
        ) as mock_get:
            await run_gdelt_geo_osint("query-connect-timeout-check", timeout_seconds=15)

        assert mock_get.call_args.kwargs["timeout"] == (_CONNECT_TIMEOUT_SECONDS, 15)
        assert _CONNECT_TIMEOUT_SECONDS < 15

    async def test_connect_timeout_fails_fast_with_clear_message(self):
        """A hang-at-connect (ConnectTimeout, a Timeout subclass) must not be
        reported as a generic read timeout — the message should make clear
        the endpoint itself is unreachable, not just slow."""
        import requests

        from openosint.tools.search_gdelt_geo import run_gdelt_geo_osint

        with patch(
            "openosint.tools.search_gdelt_geo.requests.get",
            side_effect=requests.ConnectTimeout("connect timed out"),
        ):
            result = await run_gdelt_geo_osint("query", timeout_seconds=15)

        assert "Scan error" in result
        assert "appears down" in result.lower()
        assert "15s" not in result  # must not claim the full read budget elapsed


class TestSearchGdeltGeoBboxFilter:
    def test_filters_features_outside_bbox(self):
        from openosint.tools.search_gdelt_geo import _filter_by_bbox

        inside = _gdelt_feature(30.52, 50.45, name="Kyiv, Ukraine")
        outside = _gdelt_feature(-74.0, 40.7, name="New York, USA")
        fc = _gdelt_fc([inside, outside])

        filtered = _filter_by_bbox(fc, (20.0, 40.0, 40.0, 60.0))

        names = [f["properties"]["name"] for f in filtered["features"]]
        assert "Kyiv, Ukraine" in names
        assert "New York, USA" not in names

    def test_no_bbox_returns_unchanged(self):
        from openosint.tools.search_gdelt_geo import _filter_by_bbox

        fc = _gdelt_fc([_gdelt_feature(30.52, 50.45)])
        assert _filter_by_bbox(fc, None) == fc


class TestSearchGdeltGeoProxyBypass:
    """GDELT is public/keyless/not per-IP rate-limited — it must not route
    through OPENOSINT_PROXY_URL by default, even when one is configured for
    every other tool. See openosint/tools/search_gdelt_geo.py's
    _gdelt_proxies() and _GDELT_PROXY_OPT_IN_ENV_VAR."""

    @pytest.fixture(autouse=True)
    def _reset_proxy_state(self, monkeypatch):
        from openosint import proxy

        proxy.set_cli_proxy_url(None)
        monkeypatch.delenv(proxy._ENV_VAR, raising=False)
        yield
        proxy.set_cli_proxy_url(None)

    async def test_no_proxy_kwarg_even_when_configured(self, monkeypatch):
        from openosint import proxy
        from openosint.tools.search_gdelt_geo import run_gdelt_geo_osint

        monkeypatch.setenv(proxy._ENV_VAR, "http://proxyhost:8080")
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: _gdelt_fc([])

        with patch(
            "openosint.tools.search_gdelt_geo.requests.get", return_value=mock_response
        ) as mock_get:
            await run_gdelt_geo_osint("query-proxy-bypass", timeout_seconds=5)

        assert mock_get.call_args.kwargs["proxies"] is None

    async def test_opt_in_env_var_restores_proxy(self, monkeypatch):
        from openosint import proxy
        from openosint.tools.search_gdelt_geo import run_gdelt_geo_osint

        monkeypatch.setenv(proxy._ENV_VAR, "http://proxyhost:8080")
        monkeypatch.setenv("OPENOSINT_GDELT_USE_PROXY", "1")
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: _gdelt_fc([])

        # A query string distinct from other tests in this module — GDELT
        # results are process-cached by (query, timespan, maxpoints), and a
        # repeat of another test's query would be served from cache instead
        # of hitting requests.get at all.
        with patch(
            "openosint.tools.search_gdelt_geo.requests.get", return_value=mock_response
        ) as mock_get:
            await run_gdelt_geo_osint("query-proxy-optin", timeout_seconds=5)

        assert mock_get.call_args.kwargs["proxies"] == {
            "http": "http://proxyhost:8080",
            "https": "http://proxyhost:8080",
        }

    async def test_other_tool_still_uses_configured_proxy(self, monkeypatch):
        """search_ip stands in for every other proxied tool — the shared
        default in openosint/proxy.py must be untouched by the GDELT change."""
        from openosint import proxy
        from openosint.tools.search_ip import run_ip_osint

        monkeypatch.setenv(proxy._ENV_VAR, "http://proxyhost:8080")
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {"ip": "8.8.8.8"}

        with patch(
            "openosint.tools.search_ip.requests.get", return_value=mock_response
        ) as mock_get:
            await run_ip_osint("8.8.8.8", timeout_seconds=5)

        assert mock_get.call_args.kwargs["proxies"] == {
            "http": "http://proxyhost:8080",
            "https": "http://proxyhost:8080",
        }


# ---------------------------------------------------------------------------
# search_paste — output formatting
# ---------------------------------------------------------------------------


class TestSearchPasteFormatting:
    def test_format_no_results(self):
        from openosint.tools.search_paste import _format_paste_results

        result = _format_paste_results([], "johndoe")
        assert "johndoe" in result
        assert "No pastes" in result or "no" in result.lower()

    def test_format_with_results(self):
        from openosint.tools.search_paste import _format_paste_results

        pastes = [{"id": "abc123", "time": "2026-01-01"} for _ in range(3)]
        result = _format_paste_results(pastes, "test@example.com")
        assert "pastebin.com/abc123" in result
        assert "3" in result


# ---------------------------------------------------------------------------
# search_whois — output formatting
# ---------------------------------------------------------------------------


class TestSearchWhoisFormatting:
    def test_format_no_data(self):
        from openosint.tools.search_whois import _format_whois_results

        class FakeWhois:
            domain_name = None
            registrar = None
            creation_date = None
            expiration_date = None
            updated_date = None
            name_servers = None
            emails = None
            org = None
            country = None

        result = _format_whois_results(FakeWhois(), "example.com")
        assert "example.com" in result

    def test_format_with_registrar(self):
        from openosint.tools.search_whois import _format_whois_results

        class FakeWhois:
            domain_name = "EXAMPLE.COM"
            registrar = "GoDaddy"
            creation_date = None
            expiration_date = None
            updated_date = None
            name_servers = None
            emails = None
            org = None
            country = None

        result = _format_whois_results(FakeWhois(), "example.com")
        assert "GoDaddy" in result


# ---------------------------------------------------------------------------
# search_shodan — output formatting helpers
# ---------------------------------------------------------------------------


class TestSearchShodanFormatters:
    def test_format_host_with_ports(self):
        from openosint.tools.search_shodan import _format_host

        data = {
            "ip_str": "8.8.8.8",
            "org": "Google LLC",
            "country_name": "United States",
            "data": [{"port": 80}, {"port": 443}],
        }
        result = _format_host(data, "8.8.8.8")
        assert "8.8.8.8" in result
        assert "Google" in result
        assert "80" in result

    def test_format_search_no_matches(self):
        from openosint.tools.search_shodan import _format_search

        result = _format_search({"total": 0, "matches": []}, "apache port:80")
        assert "No Shodan results" in result or "apache" in result

    def test_format_search_with_matches(self):
        from openosint.tools.search_shodan import _format_search

        results = {
            "total": 1,
            "matches": [
                {"ip_str": "1.2.3.4", "port": 80, "org": "Acme", "location": {"country_name": "US"}}
            ],
        }
        result = _format_search(results, "apache")
        assert "1.2.3.4" in result


# ---------------------------------------------------------------------------
# search_censys — API key missing + input detection
# ---------------------------------------------------------------------------


class TestSearchCensysMissingApiId:
    async def test_returns_string_when_api_id_absent(self, monkeypatch):
        monkeypatch.delenv("CENSYS_API_ID", raising=False)
        monkeypatch.delenv("CENSYS_SECRET", raising=False)
        from openosint.tools.search_censys import run_censys_osint

        result = await run_censys_osint("8.8.8.8")
        assert isinstance(result, str)

    async def test_error_mentions_censys_api_id(self, monkeypatch):
        monkeypatch.delenv("CENSYS_API_ID", raising=False)
        monkeypatch.delenv("CENSYS_SECRET", raising=False)
        from openosint.tools.search_censys import run_censys_osint

        result = await run_censys_osint("8.8.8.8")
        assert "CENSYS_API_ID" in result

    async def test_does_not_raise_when_api_id_absent(self, monkeypatch):
        monkeypatch.delenv("CENSYS_API_ID", raising=False)
        from openosint.tools.search_censys import run_censys_osint

        try:
            await run_censys_osint("8.8.8.8")
        except Exception as exc:
            pytest.fail(f"run_censys_osint raised unexpectedly: {exc}")


class TestSearchCensysMissingApiSecret:
    async def test_returns_string_when_secret_absent(self, monkeypatch):
        monkeypatch.setenv("CENSYS_API_ID", "dummy-id")
        monkeypatch.delenv("CENSYS_SECRET", raising=False)
        from openosint.tools.search_censys import run_censys_osint

        result = await run_censys_osint("8.8.8.8")
        assert isinstance(result, str)

    async def test_error_mentions_censys_secret(self, monkeypatch):
        monkeypatch.setenv("CENSYS_API_ID", "dummy-id")
        monkeypatch.delenv("CENSYS_SECRET", raising=False)
        from openosint.tools.search_censys import run_censys_osint

        result = await run_censys_osint("8.8.8.8")
        assert "CENSYS_SECRET" in result

    async def test_does_not_raise_when_secret_absent(self, monkeypatch):
        monkeypatch.setenv("CENSYS_API_ID", "dummy-id")
        monkeypatch.delenv("CENSYS_SECRET", raising=False)
        from openosint.tools.search_censys import run_censys_osint

        try:
            await run_censys_osint("8.8.8.8")
        except Exception as exc:
            pytest.fail(f"run_censys_osint raised unexpectedly: {exc}")


class TestSearchCensysInputDetection:
    def test_detects_ipv4(self):
        from openosint.tools.search_censys import _is_ip_address

        assert _is_ip_address("8.8.8.8") is True
        assert _is_ip_address("192.168.1.1") is True
        assert _is_ip_address("0.0.0.0") is True

    def test_detects_domain(self):
        from openosint.tools.search_censys import _is_ip_address

        assert _is_ip_address("example.com") is False
        assert _is_ip_address("sub.example.com") is False

    def test_non_ip_string_is_not_ip(self):
        from openosint.tools.search_censys import _is_ip_address

        assert _is_ip_address("not-an-ip") is False
        assert _is_ip_address("google.com") is False


class TestSearchCensysHandlesInvalidIp:
    async def test_does_not_raise_on_invalid_input(self, monkeypatch):
        monkeypatch.delenv("CENSYS_API_ID", raising=False)
        from openosint.tools.search_censys import run_censys_osint

        try:
            result = await run_censys_osint("999.999.999.999")
            assert isinstance(result, str)
        except Exception as exc:
            pytest.fail(f"run_censys_osint raised unexpectedly: {exc}")

    async def test_does_not_raise_on_domain(self, monkeypatch):
        monkeypatch.delenv("CENSYS_API_ID", raising=False)
        from openosint.tools.search_censys import run_censys_osint

        try:
            result = await run_censys_osint("nonexistent.example.invalid")
            assert isinstance(result, str)
        except Exception as exc:
            pytest.fail(f"run_censys_osint raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# Session history — save, load, count, clear
# ---------------------------------------------------------------------------


class TestSessionHistory:
    def test_save_and_load_round_trip(self, tmp_path, monkeypatch):
        import openosint.session_history as sh

        monkeypatch.setattr(sh, "HISTORY_DIR", tmp_path / "history")
        from openosint.session_history import SessionRecord, load_sessions, save_session

        record = SessionRecord(
            timestamp="2026-05-17T12:00:00",
            duration_seconds=42,
            prompts=["investigate test@example.com"],
            tools_used=["search_email", "search_breach"],
            targets=["test@example.com"],
            report_path="reports/2026-05-17_report.md",
        )
        save_session(record)
        sessions = load_sessions()
        assert len(sessions) == 1
        s = sessions[0]
        assert s["timestamp"] == "2026-05-17T12:00:00"
        assert s["duration_seconds"] == 42
        assert s["prompts"] == ["investigate test@example.com"]
        assert s["tools_used"] == ["search_email", "search_breach"]
        assert s["targets"] == ["test@example.com"]

    def test_load_empty_when_dir_absent(self, tmp_path, monkeypatch):
        import openosint.session_history as sh

        monkeypatch.setattr(sh, "HISTORY_DIR", tmp_path / "nonexistent")
        from openosint.session_history import load_sessions

        assert load_sessions() == []

    def test_count_sessions_zero_when_empty(self, tmp_path, monkeypatch):
        import openosint.session_history as sh

        monkeypatch.setattr(sh, "HISTORY_DIR", tmp_path / "history")
        from openosint.session_history import count_sessions

        assert count_sessions() == 0

    def test_count_sessions_after_save(self, tmp_path, monkeypatch):
        import openosint.session_history as sh

        monkeypatch.setattr(sh, "HISTORY_DIR", tmp_path / "history")
        from openosint.session_history import SessionRecord, count_sessions, save_session

        save_session(SessionRecord(timestamp="2026-05-17T10:00:00", duration_seconds=5))
        save_session(SessionRecord(timestamp="2026-05-17T11:00:00", duration_seconds=10))
        assert count_sessions() == 2

    def test_load_limit_respected(self, tmp_path, monkeypatch):
        import openosint.session_history as sh

        monkeypatch.setattr(sh, "HISTORY_DIR", tmp_path / "history")
        from openosint.session_history import SessionRecord, load_sessions, save_session

        for i in range(5):
            save_session(
                SessionRecord(
                    timestamp=f"2026-05-17T1{i}:00:00",
                    duration_seconds=i,
                )
            )
        sessions = load_sessions(limit=3)
        assert len(sessions) == 3

    def test_clear_sessions_deletes_all(self, tmp_path, monkeypatch):
        import openosint.session_history as sh

        monkeypatch.setattr(sh, "HISTORY_DIR", tmp_path / "history")
        from openosint.session_history import (
            SessionRecord,
            clear_sessions,
            count_sessions,
            save_session,
        )

        save_session(SessionRecord(timestamp="2026-05-17T12:00:00", duration_seconds=1))
        save_session(SessionRecord(timestamp="2026-05-17T13:00:00", duration_seconds=2))
        deleted = clear_sessions()
        assert deleted == 2
        assert count_sessions() == 0

    def test_clear_sessions_when_no_history(self, tmp_path, monkeypatch):
        import openosint.session_history as sh

        monkeypatch.setattr(sh, "HISTORY_DIR", tmp_path / "nonexistent")
        from openosint.session_history import clear_sessions

        assert clear_sessions() == 0

    def test_load_newest_first(self, tmp_path, monkeypatch):
        import openosint.session_history as sh

        monkeypatch.setattr(sh, "HISTORY_DIR", tmp_path / "history")
        from openosint.session_history import SessionRecord, load_sessions, save_session

        save_session(SessionRecord(timestamp="2026-05-17T09:00:00", duration_seconds=1))
        save_session(SessionRecord(timestamp="2026-05-17T11:00:00", duration_seconds=2))
        sessions = load_sessions()
        assert sessions[0]["duration_seconds"] == 2


# ---------------------------------------------------------------------------
# run_subprocess — venv-bin path resolution (fix/venv-bin-tool-discovery)
# ---------------------------------------------------------------------------


class TestRunSubprocessPathResolution:
    async def test_search_path_includes_python_executable_dir(self):
        import sys
        from pathlib import Path

        from openosint.tools.exceptions import ToolNotFoundError
        from openosint.utils import run_subprocess

        captured: dict = {}

        def spy_which(name, path=None):
            captured["path"] = path
            return None

        with patch("shutil.which", side_effect=spy_which):
            with pytest.raises(ToolNotFoundError):
                await run_subprocess("fakebinary", [], 5)

        expected_prefix = str(Path(sys.executable).parent)
        assert captured.get("path", "").startswith(expected_prefix)

    async def test_resolved_full_path_passed_to_exec(self):
        from openosint.utils import run_subprocess

        resolved_path = "/fake/venv/bin/mytool"
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"out", b"")
        mock_proc.returncode = 0

        with patch("shutil.which", return_value=resolved_path):
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
                await run_subprocess("mytool", ["--arg"], 5)

        assert mock_exec.call_args[0][0] == resolved_path
