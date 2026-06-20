# tests/test_dns.py
"""Tests for v2.15.0 — DNS intelligence integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import dns.exception
import dns.resolver

from openosint.tools.search_dns import run_dns_osint


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
