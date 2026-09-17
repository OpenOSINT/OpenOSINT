"""Unit tests for openosint-domain-recon: validation and parsing only.

Network calls (DNS/WHOIS) are always mocked — these tests never hit the
network or a real Actor run.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.main import (
    MAX_DOMAINS_PER_RUN,
    _as_list,
    _iso,
    build_domain_report,
    validate_domains,
)


class TestValidateDomains:
    def test_accepts_well_formed_domains(self):
        valid, rejected = validate_domains(["example.com", "sub.example.co.uk"])
        assert valid == ["example.com", "sub.example.co.uk"]
        assert rejected == []

    def test_rejects_malformed_domains(self):
        valid, rejected = validate_domains(["example.com", "not a domain", "no-tld", ""])
        assert valid == ["example.com"]
        assert "not a domain" in rejected
        assert "no-tld" in rejected

    def test_dedupes_case_insensitively_and_trailing_dot(self):
        valid, rejected = validate_domains(["Example.com", "example.com.", " example.com "])
        assert valid == ["example.com"]
        assert rejected == []


class TestSerializationHelpers:
    def test_iso_handles_none(self):
        assert _iso(None) is None

    def test_iso_handles_single_datetime(self):
        from datetime import datetime

        assert _iso(datetime(2020, 1, 1)) == "2020-01-01T00:00:00"

    def test_iso_handles_list_of_datetime(self):
        from datetime import datetime

        assert _iso([datetime(2020, 1, 1), datetime(2021, 1, 1)]) == "2020-01-01T00:00:00"

    def test_iso_handles_empty_list(self):
        assert _iso([]) is None

    def test_as_list_handles_none(self):
        assert _as_list(None) == []

    def test_as_list_handles_single_value(self):
        assert _as_list("ns1.example.com") == ["ns1.example.com"]

    def test_as_list_handles_list(self):
        assert _as_list(["ns1.example.com", "ns2.example.com"]) == ["ns1.example.com", "ns2.example.com"]


class TestBuildDomainReport:
    async def test_degrades_gracefully_when_whois_fails(self):
        from openosint.tools.exceptions import OSINTError
        from openosint.tools.search_dns import RecordSet

        rs = RecordSet(a=["1.2.3.4"], aaaa=[], mx=[], ns=[], txt=['"v=spf1 -all"'], cname=[], soa=[], dmarc=[], dkim_found=[])

        with (
            patch("src.main.collect_dns_records", new=AsyncMock(return_value=rs)),
            patch("src.main.fetch_whois_data", side_effect=OSINTError("WHOIS server down")),
        ):
            report = await build_domain_report("example.com")

        assert report["dnsA"] == ["1.2.3.4"]
        assert report["whoisRegistrar"] is None
        assert any("WHOIS" in w for w in report["warnings"])

    async def test_degrades_gracefully_when_dns_fails(self):
        from openosint.tools.exceptions import OSINTError

        fake_whois = type("FakeWhois", (), {"registrar": "Example Registrar", "creation_date": None, "expiration_date": None, "name_servers": None})()

        with (
            patch("src.main.collect_dns_records", side_effect=OSINTError("Domain 'example.com' does not exist.")),
            patch("src.main.fetch_whois_data", return_value=fake_whois),
        ):
            report = await build_domain_report("example.com")

        assert report["dnsA"] == []
        assert report["whoisRegistrar"] == "Example Registrar"
        assert any("DNS" in w for w in report["warnings"])

    async def test_always_includes_dork_urls(self):
        from openosint.tools.exceptions import OSINTError

        with (
            patch("src.main.collect_dns_records", side_effect=OSINTError("boom")),
            patch("src.main.fetch_whois_data", side_effect=OSINTError("boom")),
        ):
            report = await build_domain_report("example.com")

        assert len(report["dorkUrls"]) > 0
        assert all("query" in d and "url" in d for d in report["dorkUrls"])


def test_max_domains_per_run_matches_spec():
    assert MAX_DOMAINS_PER_RUN == 50
