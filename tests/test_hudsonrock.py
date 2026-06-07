# tests/test_hudsonrock.py
"""Tests for v2.20.0 — Hudson Rock infostealer integration."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from openosint.tools.search_hudsonrock import (
    _classify,
    _format_domain,
    _format_stealers,
    run_hudsonrock_osint,
)


# ---------------------------------------------------------------------------
# Fixtures grounded in the live API response shapes (probed at impl time)
# ---------------------------------------------------------------------------


def _domain_payload(stealers: int = 1000, employees: int = 50) -> dict:
    return {
        "total": 100,
        "totalStealers": stealers,
        "employees": employees,
        "users": 200,
        "third_parties": 30,
        "totalUrls": 500,
        "last_employee_compromised": "2024-11-03T08:59:11.953Z",
        "last_user_compromised": "2024-12-15T08:59:11.953Z",
        "stealerFamilies": {
            "total": stealers,
            "RedLine": 400,
            "Lumma": 350,
            "Raccoon": 150,
            "Vidar": 100,
        },
        "antiviruses": {
            "total": 312,
            "list": [
                {"count": 125, "name": "Windows Defender"},
                {"count": 60, "name": "Kaspersky"},
                {"count": 30, "name": "Avast"},
            ],
        },
    }


def _empty_domain_payload() -> dict:
    return {
        "total": 0,
        "totalStealers": 0,
        "employees": 0,
        "users": 0,
        "third_parties": 0,
    }


def _stealer_payload(n: int = 2) -> dict:
    return {
        "message": "This is a free service from Hudson Rock.",
        "total_corporate_services": 5,
        "total_user_services": 200,
        "stealers": [
            {
                "date_compromised": "2023-08-09T08:59:11.953Z",
                "computer_name": f"Dell_Laptop_{i}",
                "operating_system": "Windows 10 (10.0.19045)",
                "malware_path": "C:\\Windows\\jsc.exe",
                "antiviruses": ["Windows Defender", "Kaspersky"],
                "ip": "122.161.**.**",
                "top_passwords": ["[redacted]"] * 5,
                "top_logins": ["user@example.com", "admin@example.com"],
            }
            for i in range(n)
        ],
    }


def _empty_stealer_payload() -> dict:
    return {"stealers": [], "total_corporate_services": 0, "total_user_services": 0}


# ---------------------------------------------------------------------------
# _classify — pure routing logic
# ---------------------------------------------------------------------------


def test_classify_email() -> None:
    assert _classify("user@example.com") == "email"


def test_classify_domain() -> None:
    assert _classify("tesla.com") == "domain"


def test_classify_username_plain() -> None:
    assert _classify("johndoe99") == "username"


def test_classify_phone_e164_routes_to_username() -> None:
    assert _classify("+19777334049") == "username"


def test_classify_domain_strips_whitespace() -> None:
    assert _classify("  example.org  ") == "domain"


def test_classify_username_with_dot_in_alpha_tld_falls_to_domain() -> None:
    # Documented limitation: "user.name" looks like a domain. Acceptable —
    # SYSTEM_PROMPT instructs the agent to pass clean inputs.
    assert _classify("user.name") == "domain"


# ---------------------------------------------------------------------------
# _format_domain — output shape
# ---------------------------------------------------------------------------


def test_format_domain_includes_counts_and_warning() -> None:
    result = _format_domain("tesla.com", _domain_payload())
    assert "[HudsonRock] Query type: domain" in result
    assert "Target: tesla.com" in result
    assert "Total stealers seen: 1,000" in result
    assert "Compromised employees: 50" in result
    assert "COMPROMISED" in result
    assert "⚠️" in result


def test_format_domain_top_stealer_families() -> None:
    result = _format_domain("tesla.com", _domain_payload())
    assert "Top stealer families" in result
    assert "RedLine" in result


def test_format_domain_top_antiviruses() -> None:
    result = _format_domain("tesla.com", _domain_payload())
    assert "Windows Defender" in result


def test_format_domain_empty_payload_no_warning() -> None:
    result = _format_domain("clean.example", _empty_domain_payload())
    assert "No infostealer-compromised credentials" in result
    assert "COMPROMISED" not in result


# ---------------------------------------------------------------------------
# _format_stealers — output shape (email / username branch)
# ---------------------------------------------------------------------------


def test_format_stealers_lists_records() -> None:
    result = _format_stealers("email", "user@x.com", _stealer_payload(n=2))
    assert "Stealer records: 2" in result
    assert "Dell_Laptop_0" in result
    assert "Windows 10" in result
    assert "COMPROMISED" in result


def test_format_stealers_truncates_after_three() -> None:
    result = _format_stealers("username", "johndoe", _stealer_payload(n=10))
    assert "Stealer records: 10" in result
    assert "7 more record(s) omitted" in result


def test_format_stealers_empty_returns_no_data_message() -> None:
    result = _format_stealers("email", "clean@x.com", _empty_stealer_payload())
    assert "No infostealer-compromised credentials" in result
    assert "COMPROMISED" not in result


# ---------------------------------------------------------------------------
# run_hudsonrock_osint — routing + happy paths
# ---------------------------------------------------------------------------


async def test_email_routes_to_email_endpoint() -> None:
    with patch(
        "openosint.tools.search_hudsonrock._fetch_hudsonrock",
        new_callable=AsyncMock,
        return_value=_stealer_payload(n=1),
    ) as mock_fetch:
        result = await run_hudsonrock_osint("user@example.com")
    assert mock_fetch.await_args.args[0] == "/search-by-email"
    assert mock_fetch.await_args.args[1] == "email"
    assert "[HudsonRock]" in result


async def test_domain_routes_to_domain_endpoint() -> None:
    with patch(
        "openosint.tools.search_hudsonrock._fetch_hudsonrock",
        new_callable=AsyncMock,
        return_value=_domain_payload(),
    ) as mock_fetch:
        result = await run_hudsonrock_osint("tesla.com")
    assert mock_fetch.await_args.args[0] == "/search-by-domain"
    assert mock_fetch.await_args.args[1] == "domain"
    assert "Query type: domain" in result


async def test_username_routes_to_username_endpoint() -> None:
    with patch(
        "openosint.tools.search_hudsonrock._fetch_hudsonrock",
        new_callable=AsyncMock,
        return_value=_stealer_payload(n=1),
    ) as mock_fetch:
        await run_hudsonrock_osint("johndoe99")
    assert mock_fetch.await_args.args[0] == "/search-by-username"
    assert mock_fetch.await_args.args[1] == "username"


async def test_phone_e164_routes_to_username_endpoint() -> None:
    # Maintainer-confirmed: Hudson Rock has no separate phone endpoint;
    # phone numbers are queried via /search-by-username.
    with patch(
        "openosint.tools.search_hudsonrock._fetch_hudsonrock",
        new_callable=AsyncMock,
        return_value=_empty_stealer_payload(),
    ) as mock_fetch:
        await run_hudsonrock_osint("+19777334049")
    assert mock_fetch.await_args.args[0] == "/search-by-username"


# ---------------------------------------------------------------------------
# HUDSONROCK_API_KEY env var — passed through as Bearer auth when set
# ---------------------------------------------------------------------------


async def test_api_key_env_var_passed_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUDSONROCK_API_KEY", "secret-token")
    with patch(
        "openosint.tools.search_hudsonrock._fetch_hudsonrock",
        new_callable=AsyncMock,
        return_value=_domain_payload(),
    ) as mock_fetch:
        await run_hudsonrock_osint("tesla.com")
    assert mock_fetch.await_args.kwargs["api_key"] == "secret-token"


async def test_api_key_empty_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HUDSONROCK_API_KEY", raising=False)
    with patch(
        "openosint.tools.search_hudsonrock._fetch_hudsonrock",
        new_callable=AsyncMock,
        return_value=_domain_payload(),
    ) as mock_fetch:
        await run_hudsonrock_osint("tesla.com")
    assert mock_fetch.await_args.kwargs["api_key"] == ""


# ---------------------------------------------------------------------------
# Validation — short-circuit before network call
# ---------------------------------------------------------------------------


async def test_empty_query_no_network_call() -> None:
    with patch(
        "openosint.tools.search_hudsonrock._fetch_hudsonrock",
        new_callable=AsyncMock,
    ) as mock_fetch:
        result = await run_hudsonrock_osint("   ")
    mock_fetch.assert_not_called()
    assert "Invalid" in result


async def test_malformed_email_no_network_call() -> None:
    with patch(
        "openosint.tools.search_hudsonrock._fetch_hudsonrock",
        new_callable=AsyncMock,
    ) as mock_fetch:
        result = await run_hudsonrock_osint("user@@@")
    mock_fetch.assert_not_called()
    assert "Invalid" in result
    assert "email" in result.lower()


# ---------------------------------------------------------------------------
# Error envelope — wrapper turns exceptions into descriptive strings
# ---------------------------------------------------------------------------


async def test_timeout_returns_error_string() -> None:
    with patch(
        "openosint.tools.search_hudsonrock._fetch_hudsonrock",
        new_callable=AsyncMock,
        side_effect=asyncio.TimeoutError(),
    ):
        result = await run_hudsonrock_osint("tesla.com")
    assert "timed out" in result.lower()


async def test_network_error_returns_error_string() -> None:
    with patch(
        "openosint.tools.search_hudsonrock._fetch_hudsonrock",
        new_callable=AsyncMock,
        side_effect=aiohttp.ClientError("connection failed"),
    ):
        result = await run_hudsonrock_osint("tesla.com")
    assert "Network error" in result


async def test_value_error_returns_scan_error() -> None:
    # _raise_for_status raises ValueError on 429 / non-200; verify the wrapper
    # converts that to a "Scan error" string instead of propagating.
    with patch(
        "openosint.tools.search_hudsonrock._fetch_hudsonrock",
        new_callable=AsyncMock,
        side_effect=ValueError("Hudson Rock: rate limit exceeded (50 req / 10s)."),
    ):
        result = await run_hudsonrock_osint("tesla.com")
    assert "Scan error" in result
    assert "rate limit" in result.lower()


async def test_unexpected_error_returns_internal_error() -> None:
    with patch(
        "openosint.tools.search_hudsonrock._fetch_hudsonrock",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        result = await run_hudsonrock_osint("tesla.com")
    assert "Internal error" in result
