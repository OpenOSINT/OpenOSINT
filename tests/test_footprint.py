# tests/test_footprint.py
"""
Unit tests for search_footprint (openosint/tools/search_footprint.py)
and its Entity Correlation Graph extractor (_extract_footprint in extractors.py).

All HTTP calls are mocked — no real network requests are made.
Mock shapes match verified Bright Data SERP API behaviour:
  format=raw + data_format=parsed_light → response.json() == {"organic": [...]}
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_serp(status_code: int, json_body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    return resp


_ORGANIC_PAYLOAD = {
    "organic": [
        {
            "title": "John Doe — LinkedIn",
            "link": "https://linkedin.com/in/johndoe",
            "display_link": "linkedin.com › in › johndoe",
            "description": "Software engineer at Acme.",
        },
        {
            "title": "johndoe on GitHub",
            "link": "https://github.com/johndoe",
            "display_link": "github.com › johndoe",
            "description": "Open source projects.",
        },
    ]
}


# ---------------------------------------------------------------------------
# search_footprint: config / input validation
# ---------------------------------------------------------------------------


class TestSearchFootprintConfig:
    async def test_missing_api_key_returns_error(self, monkeypatch):
        monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
        monkeypatch.delenv("BRIGHTDATA_SERP_ZONE", raising=False)
        from openosint.tools.search_footprint import run_footprint_osint

        result = await run_footprint_osint("john doe")
        assert "BRIGHTDATA_API_KEY" in result
        assert "5,000" in result
        assert "get.brightdata.com" in result

    async def test_missing_zone_returns_error(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.delenv("BRIGHTDATA_SERP_ZONE", raising=False)
        from openosint.tools.search_footprint import run_footprint_osint

        result = await run_footprint_osint("john doe")
        assert "BRIGHTDATA_SERP_ZONE" in result
        assert "get.brightdata.com" in result

    async def test_empty_target_returns_error(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp1")
        from openosint.tools.search_footprint import run_footprint_osint

        result = await run_footprint_osint("   ")
        assert "invalid" in result.lower() or "empty" in result.lower()

    async def test_unsupported_ip_target_returns_error(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "test-key")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp1")
        from openosint.tools.search_footprint import run_footprint_osint

        result = await run_footprint_osint("8.8.8.8")
        assert "not supported" in result.lower() or "unsupported" in result.lower()

    async def test_does_not_raise_on_missing_key(self, monkeypatch):
        monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
        monkeypatch.delenv("BRIGHTDATA_SERP_ZONE", raising=False)
        from openosint.tools.search_footprint import run_footprint_osint

        result = await run_footprint_osint("target")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# search_footprint: entity-type detection
# ---------------------------------------------------------------------------


class TestSearchFootprintEntityDetection:
    async def test_email_query_uses_exact_match_template(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(200, {"organic": []})
        with patch(
            "openosint.tools.search_footprint.requests.post", return_value=mock_resp
        ) as mock_post:
            from openosint.tools.search_footprint import run_footprint_osint

            await run_footprint_osint("user@example.com", max_queries=1)

        posted_url = mock_post.call_args.kwargs["json"]["url"]
        assert "user%40example.com" in posted_url or "user@example.com" in posted_url

    async def test_domain_query_uses_site_operator(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(200, {"organic": []})
        with patch(
            "openosint.tools.search_footprint.requests.post", return_value=mock_resp
        ) as mock_post:
            from openosint.tools.search_footprint import run_footprint_osint

            await run_footprint_osint("example.com", max_queries=1)

        posted_url = mock_post.call_args.kwargs["json"]["url"]
        assert "site%3Aexample.com" in posted_url or "site:example.com" in posted_url

    async def test_output_shows_detected_entity_type_email(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(200, {"organic": []})
        with patch("openosint.tools.search_footprint.requests.post", return_value=mock_resp):
            from openosint.tools.search_footprint import run_footprint_osint

            result = await run_footprint_osint("user@example.com", max_queries=1)

        assert result["target_type"] == "email"

    async def test_output_shows_detected_entity_type_username(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(200, {"organic": []})
        with patch("openosint.tools.search_footprint.requests.post", return_value=mock_resp):
            from openosint.tools.search_footprint import run_footprint_osint

            result = await run_footprint_osint("johndoe99", max_queries=1)

        assert result["target_type"] == "username"

    async def test_full_name_detected_as_person(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(200, {"organic": []})
        with patch("openosint.tools.search_footprint.requests.post", return_value=mock_resp):
            from openosint.tools.search_footprint import run_footprint_osint

            result = await run_footprint_osint("John Doe", max_queries=1)

        assert result["target_type"] == "person"


# ---------------------------------------------------------------------------
# search_footprint: SERP results
# ---------------------------------------------------------------------------


class TestSearchFootprintResults:
    async def test_success_returns_title_and_url(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(200, _ORGANIC_PAYLOAD)
        with patch("openosint.tools.search_footprint.requests.post", return_value=mock_resp):
            from openosint.tools.search_footprint import run_footprint_osint

            result = await run_footprint_osint("john doe", max_queries=1)

        assert any("linkedin.com/in/johndoe" in url for url in result["discovered_urls"])

    async def test_deduplicates_urls_across_queries(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(200, _ORGANIC_PAYLOAD)
        with patch("openosint.tools.search_footprint.requests.post", return_value=mock_resp):
            from openosint.tools.search_footprint import run_footprint_osint

            result = await run_footprint_osint("john doe", max_queries=2)

        assert result["discovered_urls"].count("https://linkedin.com/in/johndoe") == 1

    async def test_no_organic_shows_placeholder(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(200, {"organic": []})
        with patch("openosint.tools.search_footprint.requests.post", return_value=mock_resp):
            from openosint.tools.search_footprint import run_footprint_osint

            result = await run_footprint_osint("john doe", max_queries=1)

        assert result["discovered_urls"] == []

    async def test_request_uses_format_raw_and_parsed_light(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(200, {"organic": []})
        with patch(
            "openosint.tools.search_footprint.requests.post", return_value=mock_resp
        ) as mock_post:
            from openosint.tools.search_footprint import run_footprint_osint

            await run_footprint_osint("john doe", max_queries=1)

        payload = mock_post.call_args.kwargs["json"]
        assert payload.get("format") == "raw"
        assert payload.get("data_format") == "parsed_light"

    async def test_google_url_has_q_first(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(200, {"organic": []})
        with patch(
            "openosint.tools.search_footprint.requests.post", return_value=mock_resp
        ) as mock_post:
            from openosint.tools.search_footprint import run_footprint_osint

            await run_footprint_osint("john doe", max_queries=1)

        google_url = mock_post.call_args.kwargs["json"]["url"]
        assert "?q=" in google_url
        assert google_url.index("?q=") < google_url.index("&") if "&" in google_url else True

    async def test_max_queries_limits_api_calls(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(200, {"organic": []})
        with patch(
            "openosint.tools.search_footprint.requests.post", return_value=mock_resp
        ) as mock_post:
            from openosint.tools.search_footprint import run_footprint_osint

            await run_footprint_osint("john doe", max_queries=2)

        assert mock_post.call_count == 2


# ---------------------------------------------------------------------------
# search_footprint: HTTP error handling
# ---------------------------------------------------------------------------


class TestSearchFootprintHttpErrors:
    async def test_http_401_returns_error(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "bad")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(401)
        with patch("openosint.tools.search_footprint.requests.post", return_value=mock_resp):
            from openosint.tools.search_footprint import run_footprint_osint

            result = await run_footprint_osint("john doe", max_queries=1)

        assert "error" in result.lower()

    async def test_http_429_returns_error(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(429)
        with patch("openosint.tools.search_footprint.requests.post", return_value=mock_resp):
            from openosint.tools.search_footprint import run_footprint_osint

            result = await run_footprint_osint("john doe", max_queries=1)

        assert "error" in result.lower()

    async def test_all_queries_fail_returns_scan_error(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(500)
        with patch("openosint.tools.search_footprint.requests.post", return_value=mock_resp):
            from openosint.tools.search_footprint import run_footprint_osint

            result = await run_footprint_osint("john doe", max_queries=2)

        assert "Scan error" in result

    async def test_network_exception_handled_gracefully(self, monkeypatch):
        import requests as _requests

        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        with patch(
            "openosint.tools.search_footprint.requests.post",
            side_effect=_requests.RequestException("timeout"),
        ):
            from openosint.tools.search_footprint import run_footprint_osint

            result = await run_footprint_osint("john doe", max_queries=1)

        assert isinstance(result, str)
        assert "error" in result.lower()


# ---------------------------------------------------------------------------
# search_footprint: graph output lines
# ---------------------------------------------------------------------------


class TestSearchFootprintGraphLines:
    async def test_footprint_url_lines_present(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(200, _ORGANIC_PAYLOAD)
        with patch("openosint.tools.search_footprint.requests.post", return_value=mock_resp):
            from openosint.tools.search_footprint import run_footprint_osint

            result = await run_footprint_osint("john doe", max_queries=1)

        assert "https://linkedin.com/in/johndoe" in result["discovered_urls"]
        assert "https://github.com/johndoe" in result["discovered_urls"]

    async def test_domain_lines_emitted(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(200, _ORGANIC_PAYLOAD)
        with patch("openosint.tools.search_footprint.requests.post", return_value=mock_resp):
            from openosint.tools.search_footprint import run_footprint_osint

            result = await run_footprint_osint("john doe", max_queries=1)

        assert "linkedin.com" in result["seen_domains"]
        assert "github.com" in result["seen_domains"]

    async def test_no_graph_lines_when_no_results(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
        monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
        mock_resp = _mock_serp(200, {"organic": []})
        with patch("openosint.tools.search_footprint.requests.post", return_value=mock_resp):
            from openosint.tools.search_footprint import run_footprint_osint

            result = await run_footprint_osint("john doe", max_queries=1)

        assert result["discovered_urls"] == []


# ---------------------------------------------------------------------------
# Entity Correlation Graph extractor
# ---------------------------------------------------------------------------


class TestExtractFootprint:
    def _seed(self):
        from openosint.correlation import EntityType, make_entity

        return make_entity(EntityType.USERNAME, "johndoe", 1.0, "test")

    def test_extracts_url_entities(self):
        from openosint.extractors import _extract_footprint

        raw = (
            "[Footprint] johndoe  |  type: username  |  1 query\n"
            "[Footprint] URL: https://linkedin.com/in/johndoe\n"
            "[Footprint] Domain: linkedin.com\n"
        )
        entities, _ = _extract_footprint(raw, self._seed())
        url_entities = [e for e in entities if e.type.value == "url"]
        assert len(url_entities) == 1
        assert url_entities[0].value == "https://linkedin.com/in/johndoe"

    def test_extracts_domain_entities(self):
        from openosint.extractors import _extract_footprint

        raw = (
            "[Footprint] URL: https://linkedin.com/in/johndoe\n"
            "[Footprint] Domain: linkedin.com\n"
        )
        entities, _ = _extract_footprint(raw, self._seed())
        domain_entities = [e for e in entities if e.type.value == "domain"]
        assert len(domain_entities) == 1
        assert domain_entities[0].value == "linkedin.com"

    def test_url_relationship_kind_is_found_via_serp(self):
        from openosint.extractors import _extract_footprint

        raw = "[Footprint] URL: https://twitter.com/johndoe\n"
        _, rels = _extract_footprint(raw, self._seed())
        url_rels = [r for r in rels if r.kind == "found_via_serp"]
        assert len(url_rels) == 1

    def test_domain_relationship_kind_is_footprint_on(self):
        from openosint.extractors import _extract_footprint

        raw = "[Footprint] Domain: twitter.com\n"
        _, rels = _extract_footprint(raw, self._seed())
        domain_rels = [r for r in rels if r.kind == "footprint_on"]
        assert len(domain_rels) == 1

    def test_empty_raw_returns_empty_lists(self):
        from openosint.extractors import _extract_footprint

        entities, rels = _extract_footprint("", self._seed())
        assert entities == []
        assert rels == []

    def test_deduplicates_domains(self):
        from openosint.extractors import _extract_footprint

        raw = (
            "[Footprint] Domain: linkedin.com\n"
            "[Footprint] Domain: linkedin.com\n"
        )
        entities, _ = _extract_footprint(raw, self._seed())
        domain_entities = [e for e in entities if e.type.value == "domain"]
        assert len(domain_entities) == 1

    def test_source_tool_is_search_footprint(self):
        from openosint.extractors import _extract_footprint

        raw = "[Footprint] URL: https://github.com/johndoe\n"
        entities, _ = _extract_footprint(raw, self._seed())
        assert all("search_footprint" in e.source_tools for e in entities)

    def test_extractor_registered_in_registry(self):
        from openosint.extractors import EXTRACTOR_REGISTRY

        assert "search_footprint" in EXTRACTOR_REGISTRY


# ---------------------------------------------------------------------------
# regexes.detect_entity_kind
# ---------------------------------------------------------------------------


class TestDetectEntityKind:
    def test_email(self):
        from openosint.regexes import detect_entity_kind

        assert detect_entity_kind("user@example.com") == "email"

    def test_domain(self):
        from openosint.regexes import detect_entity_kind

        assert detect_entity_kind("example.com") == "domain"

    def test_ipv4(self):
        from openosint.regexes import detect_entity_kind

        assert detect_entity_kind("192.168.1.1") == "ip"

    def test_phone(self):
        from openosint.regexes import detect_entity_kind

        assert detect_entity_kind("+14155552671") == "phone"

    def test_username(self):
        from openosint.regexes import detect_entity_kind

        assert detect_entity_kind("johndoe99") == "username"

    def test_full_name_is_person(self):
        from openosint.regexes import detect_entity_kind

        assert detect_entity_kind("John Doe") == "person"

    def test_hash_md5(self):
        from openosint.regexes import detect_entity_kind

        assert detect_entity_kind("d41d8cd98f00b204e9800998ecf8427e") == "hash"

    def test_url(self):
        from openosint.regexes import detect_entity_kind

        assert detect_entity_kind("https://example.com") == "url"
