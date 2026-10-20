"""Tests for openosint/tools/search_rdap.py — used by the domain-recon Actor.

All network calls (requests.get) are mocked — no real HTTP traffic.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from openosint.tools.exceptions import OSINTError, ToolExecutionError
from openosint.tools.search_rdap import (
    fetch_rdap_bootstrap,
    fetch_rdap_data,
    parse_rdap_domain,
)
import openosint.tools.search_rdap as search_rdap

_BOOTSTRAP_RESPONSE = {
    "services": [
        [["com", "net"], ["https://rdap.verisign.com/com/v1/"]],
        [["example"], ["https://rdap.example-registry.test/", "https://rdap-backup.example-registry.test/"]],
    ]
}

_SAMPLE_RDAP_DOMAIN = {
    "objectClassName": "domain",
    "handle": "2336799_DOMAIN_COM-VRSN",
    "ldhName": "EXAMPLE.COM",
    "status": ["client delete prohibited", "client transfer prohibited"],
    "entities": [
        {
            "objectClassName": "entity",
            "roles": ["registrar"],
            "vcardArray": [
                "vcard",
                [
                    ["version", {}, "text", "4.0"],
                    ["fn", {}, "text", "RESERVED-Internet Assigned Numbers Authority"],
                ],
            ],
        }
    ],
    "nameservers": [
        {"objectClassName": "nameserver", "ldhName": "B.IANA-SERVERS.NET"},
        {"objectClassName": "nameserver", "ldhName": "A.IANA-SERVERS.NET"},
    ],
    "events": [
        {"eventAction": "registration", "eventDate": "1995-08-14T04:00:00Z"},
        {"eventAction": "expiration", "eventDate": "2027-08-13T04:00:00Z"},
        {"eventAction": "last changed", "eventDate": "2024-08-14T07:01:44Z"},
    ],
}


@pytest.fixture(autouse=True)
def _clear_bootstrap_cache():
    search_rdap._bootstrap_cache.clear()
    yield
    search_rdap._bootstrap_cache.clear()


class TestFetchRdapBootstrap:
    def test_parses_services_into_tld_mapping(self):
        with patch("requests.get", return_value=Mock(status_code=200, json=lambda: _BOOTSTRAP_RESPONSE)):
            mapping = fetch_rdap_bootstrap()
        assert mapping["com"] == ["https://rdap.verisign.com/com/v1/"]
        assert mapping["net"] == ["https://rdap.verisign.com/com/v1/"]

    def test_caches_result_across_calls(self):
        mock_get = Mock(return_value=Mock(status_code=200, json=lambda: _BOOTSTRAP_RESPONSE))
        with patch("requests.get", mock_get):
            fetch_rdap_bootstrap()
            fetch_rdap_bootstrap()
        assert mock_get.call_count == 1

    def test_raises_osint_error_on_network_failure(self):
        with patch("requests.get", side_effect=requests.RequestException("conn refused")):
            with pytest.raises(OSINTError, match="Failed to fetch"):
                fetch_rdap_bootstrap()

    def test_raises_tool_execution_error_on_non_200(self):
        with patch("requests.get", return_value=Mock(status_code=503)):
            with pytest.raises(ToolExecutionError, match="503"):
                fetch_rdap_bootstrap()

    def test_raises_tool_execution_error_on_malformed_json(self):
        bad_response = Mock(status_code=200)
        bad_response.json.side_effect = ValueError("bad json")
        with patch("requests.get", return_value=bad_response):
            with pytest.raises(ToolExecutionError, match="malformed JSON"):
                fetch_rdap_bootstrap()


class TestFetchRdapData:
    def test_returns_json_on_200(self):
        bootstrap = {"com": ["https://rdap.verisign.com/com/v1/"]}
        with patch("requests.get", return_value=Mock(status_code=200, json=lambda: _SAMPLE_RDAP_DOMAIN)):
            data = fetch_rdap_data("example.com", bootstrap)
        assert data == _SAMPLE_RDAP_DOMAIN

    def test_raises_osint_error_on_404(self):
        bootstrap = {"com": ["https://rdap.verisign.com/com/v1/"]}
        with patch("requests.get", return_value=Mock(status_code=404)):
            with pytest.raises(OSINTError, match="not registered"):
                fetch_rdap_data("thisdomaindoesnotexist-test.com", bootstrap)

    def test_raises_osint_error_for_unknown_tld(self):
        with pytest.raises(OSINTError, match="No RDAP server"):
            fetch_rdap_data("example.zzznotarealtld", bootstrap={})

    def test_falls_back_to_second_base_url_on_failure(self):
        bootstrap = {"example": ["https://rdap-down.test/", "https://rdap-up.test/"]}
        responses = [Mock(status_code=503), Mock(status_code=200, json=lambda: _SAMPLE_RDAP_DOMAIN)]
        with patch("requests.get", side_effect=responses):
            data = fetch_rdap_data("example.example", bootstrap)
        assert data == _SAMPLE_RDAP_DOMAIN


class TestParseRdapDomain:
    def test_extracts_registrar_from_vcard_fn(self):
        result = parse_rdap_domain(_SAMPLE_RDAP_DOMAIN)
        assert result["registrar"] == "RESERVED-Internet Assigned Numbers Authority"

    def test_extracts_created_and_expires_dates(self):
        result = parse_rdap_domain(_SAMPLE_RDAP_DOMAIN)
        assert result["createdDate"] == "1995-08-14T04:00:00Z"
        assert result["expiresDate"] == "2027-08-13T04:00:00Z"

    def test_extracts_and_normalizes_name_servers(self):
        result = parse_rdap_domain(_SAMPLE_RDAP_DOMAIN)
        assert result["nameServers"] == ["a.iana-servers.net", "b.iana-servers.net"]

    def test_extracts_status(self):
        result = parse_rdap_domain(_SAMPLE_RDAP_DOMAIN)
        assert result["status"] == ["client delete prohibited", "client transfer prohibited"]

    def test_never_reads_registrant_contact_fields(self):
        result = parse_rdap_domain(_SAMPLE_RDAP_DOMAIN)
        assert set(result.keys()) == {"registrar", "createdDate", "expiresDate", "nameServers", "status"}

    def test_handles_empty_response_gracefully(self):
        result = parse_rdap_domain({})
        assert result == {
            "registrar": None,
            "createdDate": None,
            "expiresDate": None,
            "nameServers": [],
            "status": [],
        }
