# tests/test_dns.py
"""Tests for v2.15.0 — DNS intelligence integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import dns.exception
import dns.resolver
import pytest

from openosint.tools.search_dns import (
    RecordSet,
    _is_valid_dkim_record,
    _probe_dkim,
    compute_email_security_grade,
    run_dns_osint,
)


def _answers(strings: list[str]) -> list[MagicMock]:
    """Return mock DNS answer records that stringify to *strings*."""
    return [MagicMock(__str__=lambda self, s=s: s) for s in strings]


def _make_side_effect(mapping: dict[tuple[str, str], list[str]]):
    """Build a dns.resolver.resolve side_effect from a {(domain, rdtype): [str]} map."""

    def _resolve(domain: str, rdtype: str):
        key = (domain, rdtype)
        values = mapping.get(key)
        if values:
            return _answers(values)
        raise dns.resolver.NoAnswer()

    return _resolve


def _sync_executor(loop_mock, fn):
    """Make run_in_executor call *fn* synchronously and return its result."""
    result = fn()

    async def _coro():
        return result

    return _coro()


# ---------------------------------------------------------------------------
# NXDOMAIN
# ---------------------------------------------------------------------------


async def test_nxdomain_returns_does_not_exist() -> None:
    with patch("openosint.tools.search_dns.dns.resolver.Resolver") as MockResolver:
        instance = MockResolver.return_value
        instance.resolve.side_effect = dns.resolver.NXDOMAIN()
        result = await run_dns_osint("nonexistent.invalid")
    assert "does not exist" in result


# ---------------------------------------------------------------------------
# Standard domain — key record types present in output
# ---------------------------------------------------------------------------


async def test_standard_domain_has_a_mx_ns() -> None:
    mapping: dict[tuple[str, str], list[str]] = {
        ("example.com", "A"): ["93.184.216.34"],
        ("example.com", "MX"): ["10 mail.example.com."],
        ("example.com", "NS"): ["ns1.example.com.", "ns2.example.com."],
        ("example.com", "TXT"): ['"v=spf1 include:_spf.example.com -all"'],
        ("example.com", "SOA"): ["ns1.example.com. admin.example.com. 2024010101 3600 900 604800 300"],
        ("_dmarc.example.com", "TXT"): ['"v=DMARC1; p=reject; rua=mailto:dmarc@example.com"'],
    }

    with patch("openosint.tools.search_dns.dns.resolver.Resolver") as MockResolver:
        instance = MockResolver.return_value
        instance.resolve.side_effect = _make_side_effect(mapping)

        with patch("openosint.tools.search_dns.asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor.side_effect = _sync_executor
            result = await run_dns_osint("example.com")

    assert "A:" in result
    assert "MX" in result
    assert "NS:" in result


# ---------------------------------------------------------------------------
# Missing SPF
# ---------------------------------------------------------------------------


async def test_missing_spf_shows_warning() -> None:
    mapping: dict[tuple[str, str], list[str]] = {
        ("nospf.example", "A"): ["1.2.3.4"],
        ("nospf.example", "TXT"): ['"some-other-record"'],
    }

    with patch("openosint.tools.search_dns.dns.resolver.Resolver") as MockResolver:
        instance = MockResolver.return_value
        instance.resolve.side_effect = _make_side_effect(mapping)

        with patch("openosint.tools.search_dns.asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor.side_effect = _sync_executor
            result = await run_dns_osint("nospf.example")

    assert "[!] No SPF record" in result


# ---------------------------------------------------------------------------
# SPF with +all — weak policy warning
# ---------------------------------------------------------------------------


async def test_spf_plus_all_shows_warning() -> None:
    mapping: dict[tuple[str, str], list[str]] = {
        ("weak.example", "A"): ["1.2.3.4"],
        ("weak.example", "TXT"): ['"v=spf1 +all"'],
    }

    with patch("openosint.tools.search_dns.dns.resolver.Resolver") as MockResolver:
        instance = MockResolver.return_value
        instance.resolve.side_effect = _make_side_effect(mapping)

        with patch("openosint.tools.search_dns.asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor.side_effect = _sync_executor
            result = await run_dns_osint("weak.example")

    assert "[!] SPF uses +all" in result


# ---------------------------------------------------------------------------
# Missing DMARC
# ---------------------------------------------------------------------------


async def test_missing_dmarc_shows_warning() -> None:
    mapping: dict[tuple[str, str], list[str]] = {
        ("nodmarc.example", "A"): ["1.2.3.4"],
        ("nodmarc.example", "TXT"): ['"v=spf1 -all"'],
        # _dmarc.nodmarc.example is intentionally absent → NoAnswer
    }

    with patch("openosint.tools.search_dns.dns.resolver.Resolver") as MockResolver:
        instance = MockResolver.return_value
        instance.resolve.side_effect = _make_side_effect(mapping)

        with patch("openosint.tools.search_dns.asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor.side_effect = _sync_executor
            result = await run_dns_osint("nodmarc.example")

    assert "[!] No DMARC policy found" in result


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


async def test_timeout_returns_error_string() -> None:
    with patch("openosint.tools.search_dns.dns.resolver.Resolver") as MockResolver:
        instance = MockResolver.return_value
        instance.resolve.side_effect = dns.exception.Timeout()
        result = await run_dns_osint("slow.example")
    assert "timed out" in result.lower() or "timeout" in result.lower()


# ---------------------------------------------------------------------------
# compute_email_security_grade — pure logic, used by the domain-recon Actor
# ---------------------------------------------------------------------------


def _record_set(**overrides) -> RecordSet:
    defaults = dict(a=[], aaaa=[], mx=[], ns=[], txt=[], cname=[], soa=[], dmarc=[], dkim_found=[])
    defaults.update(overrides)
    return RecordSet(**defaults)


class TestComputeEmailSecurityGrade:
    def test_fully_configured_domain_gets_a(self):
        rs = _record_set(
            txt=['"v=spf1 -all"'],
            dmarc=['"v=DMARC1; p=reject"'],
            dkim_found=["default: v=DKIM1; k=rsa; p=..."],
        )
        grade, issues = compute_email_security_grade(rs, spf_warnings=[], dmarc_warnings=[])
        assert grade == "A"
        assert issues == []

    def test_missing_spf_is_worst_case_f(self):
        rs = _record_set(dmarc=['"v=DMARC1; p=reject"'], dkim_found=["default: ..."])
        grade, issues = compute_email_security_grade(rs, spf_warnings=[], dmarc_warnings=[])
        assert grade == "F"
        assert any("SPF" in issue for issue in issues)

    def test_missing_dmarc_caps_at_d(self):
        rs = _record_set(txt=['"v=spf1 -all"'], dkim_found=["default: ..."])
        grade, issues = compute_email_security_grade(rs, spf_warnings=[], dmarc_warnings=[])
        assert grade == "D"
        assert any("DMARC" in issue for issue in issues)

    def test_missing_dkim_caps_at_c(self):
        rs = _record_set(txt=['"v=spf1 -all"'], dmarc=['"v=DMARC1; p=reject"'])
        grade, issues = compute_email_security_grade(rs, spf_warnings=[], dmarc_warnings=[])
        assert grade == "C"
        assert any("DKIM" in issue for issue in issues)

    def test_dkim_wildcard_caps_at_c_even_with_selectors_reported(self):
        # dkim_found should always be empty when dkim_wildcard is True in practice,
        # but the grader itself must not trust dkim_found when the flag is set.
        rs = _record_set(
            txt=['"v=spf1 -all"'],
            dmarc=['"v=DMARC1; p=reject"'],
            dkim_found=["default: v=DKIM1; p=fake"],
            dkim_wildcard=True,
        )
        grade, issues = compute_email_security_grade(rs, spf_warnings=[], dmarc_warnings=[])
        assert grade == "C"
        assert any("wildcard" in issue.lower() for issue in issues)


# ---------------------------------------------------------------------------
# _probe_dkim / _is_valid_dkim_record — wildcard and revoked-key handling
# ---------------------------------------------------------------------------


class TestIsValidDkimRecord:
    def test_accepts_a_real_looking_key(self):
        assert _is_valid_dkim_record("v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUA") is True

    def test_rejects_empty_p_tag_with_trailing_semicolon(self):
        assert _is_valid_dkim_record("v=DKIM1; p=;") is False

    def test_rejects_empty_p_tag_at_end_of_string(self):
        assert _is_valid_dkim_record("v=DKIM1; k=rsa; p=") is False

    def test_rejects_record_with_no_dkim_markers_at_all(self):
        assert _is_valid_dkim_record("just some unrelated txt record") is False


def _dkim_side_effect(known_selector_answers: dict[str, list[str]], wildcard_answer: list[str] | None):
    """Resolver.resolve side_effect: known selectors get their mapped answer;
    any *other* _domainkey query (the random wildcard probe) gets wildcard_answer,
    or NoAnswer if wildcard_answer is None."""

    def _resolve(name: str, rdtype: str):
        if "_domainkey." in name and rdtype == "TXT":
            selector = name.split("._domainkey.")[0]
            if selector in known_selector_answers:
                return _answers(known_selector_answers[selector])
            if wildcard_answer is not None:
                return _answers(wildcard_answer)
        raise dns.resolver.NoAnswer()

    return _resolve


class TestProbeDkimWildcard:
    def test_no_wildcard_reports_real_selector_matches(self):
        resolver = MagicMock()
        resolver.resolve.side_effect = _dkim_side_effect(
            known_selector_answers={"default": ['"v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3"']},
            wildcard_answer=None,
        )
        found, wildcard = _probe_dkim(resolver, "example.com")
        assert wildcard is False
        assert any("default" in f for f in found)

    def test_wildcard_domain_reports_no_selectors(self):
        resolver = MagicMock()
        resolver.resolve.side_effect = _dkim_side_effect(
            known_selector_answers={"default": ['"v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3"']},
            wildcard_answer=['"v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3"'],
        )
        found, wildcard = _probe_dkim(resolver, "wildcard.example.com")
        assert wildcard is True
        assert found == []

    def test_revoked_key_at_a_real_selector_is_not_counted(self):
        resolver = MagicMock()
        resolver.resolve.side_effect = _dkim_side_effect(
            known_selector_answers={"default": ['"v=DKIM1; k=rsa; p="']},
            wildcard_answer=None,
        )
        found, wildcard = _probe_dkim(resolver, "example.com")
        assert wildcard is False
        assert found == []
