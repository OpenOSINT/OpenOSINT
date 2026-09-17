"""Unit tests for openosint-domain-recon: validation and parsing only.

Network calls (DNS/RDAP) are always mocked — these tests never hit the
network or a real Actor run.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.main import (
    MAX_DOMAINS_PER_RUN,
    build_domain_report,
    validate_domains,
)


def _record_set(**overrides):
    from openosint.tools.search_dns import RecordSet

    defaults = dict(a=[], aaaa=[], mx=[], ns=[], txt=[], cname=[], soa=[], dmarc=[], dkim_found=[], dkim_wildcard=False)
    defaults.update(overrides)
    return RecordSet(**defaults)


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


class TestBuildDomainReport:
    async def test_degrades_gracefully_when_rdap_fails(self):
        from openosint.tools.exceptions import OSINTError

        rs = _record_set(a=["1.2.3.4"], ns=["ns1.example.com"], txt=['"v=spf1 -all"'])

        with (
            patch("src.main.collect_dns_records", new=AsyncMock(return_value=rs)),
            patch("src.main.fetch_rdap_data", side_effect=OSINTError("RDAP server down")),
        ):
            report = await build_domain_report("example.com", rdap_bootstrap={"com": ["https://rdap.test/"]})

        assert report["dnsA"] == ["1.2.3.4"]
        assert report["rdapRegistrar"] is None
        assert report["domainExists"] is True
        assert any("RDAP" in w for w in report["warnings"])

    async def test_degrades_gracefully_when_dns_fails(self):
        from openosint.tools.exceptions import OSINTError

        with (
            patch("src.main.collect_dns_records", side_effect=OSINTError("Domain 'example.com' does not exist.")),
            patch(
                "src.main.fetch_rdap_data",
                return_value={"entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["fn", {}, "text", "Example Registrar"]]]}]},
            ),
        ):
            report = await build_domain_report("example.com", rdap_bootstrap={"com": ["https://rdap.test/"]})

        assert report["dnsA"] == []
        assert report["rdapRegistrar"] == "Example Registrar"
        # DNS's NXDOMAIN verdict is authoritative — an RDAP hit doesn't override it.
        assert report["domainExists"] is False
        assert any("DNS" in w for w in report["warnings"])

    async def test_domain_exists_true_when_ns_or_soa_present(self):
        rs = _record_set(ns=["ns1.example.com"])
        with (
            patch("src.main.collect_dns_records", new=AsyncMock(return_value=rs)),
            patch("src.main.fetch_rdap_data", return_value={}),
        ):
            report = await build_domain_report("example.com", rdap_bootstrap={"com": ["https://rdap.test/"]})
        assert report["domainExists"] is True

    async def test_rdap_fallback_marks_nonexistent_when_dns_is_ambiguous(self):
        from openosint.tools.exceptions import OSINTError

        with (
            patch("src.main.collect_dns_records", side_effect=OSINTError("DNS query timed out after 10s.")),
            patch("src.main.fetch_rdap_data", side_effect=OSINTError("Domain 'x.com' is not registered (RDAP 404).")),
        ):
            report = await build_domain_report("x.com", rdap_bootstrap={"com": ["https://rdap.test/"]})
        assert report["domainExists"] is False

    async def test_dns_timeout_alone_leaves_domain_exists_unknown(self):
        from openosint.tools.exceptions import OSINTError

        with (
            patch("src.main.collect_dns_records", side_effect=OSINTError("DNS query timed out after 10s.")),
            patch("src.main.fetch_rdap_data", side_effect=OSINTError("RDAP server down")),
        ):
            report = await build_domain_report("x.com", rdap_bootstrap={"com": ["https://rdap.test/"]})
        assert report["domainExists"] is None

    async def test_rdap_skipped_when_bootstrap_unavailable(self):
        rs = _record_set(ns=["ns1.example.com"])
        with patch("src.main.collect_dns_records", new=AsyncMock(return_value=rs)):
            report = await build_domain_report("example.com", rdap_bootstrap=None)
        assert report["rdapRegistrar"] is None
        assert any("RDAP lookup skipped" in w for w in report["warnings"])

    async def test_dkim_wildcard_flows_through_to_report(self):
        rs = _record_set(ns=["ns1.example.com"], txt=['"v=spf1 -all"'], dkim_wildcard=True)
        with (
            patch("src.main.collect_dns_records", new=AsyncMock(return_value=rs)),
            patch("src.main.fetch_rdap_data", return_value={}),
        ):
            report = await build_domain_report("example.com", rdap_bootstrap={"com": ["https://rdap.test/"]})
        assert report["dkimWildcard"] is True
        assert report["dkimSelectorsFound"] == []

    async def test_always_includes_dork_urls(self):
        from openosint.tools.exceptions import OSINTError

        with (
            patch("src.main.collect_dns_records", side_effect=OSINTError("boom")),
            patch("src.main.fetch_rdap_data", side_effect=OSINTError("boom")),
        ):
            report = await build_domain_report("example.com", rdap_bootstrap={"com": ["https://rdap.test/"]})

        assert len(report["dorkUrls"]) > 0
        assert all("query" in d and "url" in d for d in report["dorkUrls"])


def test_max_domains_per_run_matches_spec():
    assert MAX_DOMAINS_PER_RUN == 50
