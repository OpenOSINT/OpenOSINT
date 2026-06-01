# tests/test_sherlockeye.py
"""Tests for Sherlockeye integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from openosint.tools.search_sherlockeye import (
    _infer_search_type,
    _parse_query,
    run_sherlockeye_osint,
)


def test_parse_explicit_email() -> None:
    assert _parse_query('email:"user@example.com"') == ("email", "user@example.com")


def test_parse_explicit_unquoted() -> None:
    assert _parse_query("domain:example.com") == ("domain", "example.com")


def test_infer_email() -> None:
    assert _infer_search_type("user@example.com") == "email"


def test_infer_ip() -> None:
    assert _infer_search_type("8.8.8.8") == "ip"


def test_infer_name() -> None:
    assert _infer_search_type("John Doe") == "name"


async def test_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHERLOCKEYE_API_KEY", raising=False)
    result = await run_sherlockeye_osint("user@example.com")
    assert "Scan error" in result
    assert "SHERLOCKEYE_API_KEY" in result


async def test_empty_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHERLOCKEYE_API_KEY", "test-key")
    result = await run_sherlockeye_osint("   ")
    assert "Scan error" in result


async def test_successful_sync_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHERLOCKEYE_API_KEY", "test-key")
    mock_data = {
        "searchId": "abc123",
        "type": "email",
        "value": "user@example.com",
        "status": "complete",
        "progress": 100,
        "results": [
            {
                "id": "1",
                "source": "example_source",
                "attributes": {"email": "user@example.com", "name": "User"},
            }
        ],
    }
    with patch(
        "openosint.tools.search_sherlockeye._create_sync_search",
        new_callable=AsyncMock,
        return_value=mock_data,
    ):
        result = await run_sherlockeye_osint("user@example.com", timeout_seconds=30)
    assert "[Sherlockeye]" in result
    assert "example_source" in result
    assert "user@example.com" in result


async def test_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHERLOCKEYE_API_KEY", "test-key")
    with patch(
        "openosint.tools.search_sherlockeye._create_sync_search",
        new_callable=AsyncMock,
        side_effect=aiohttp.ClientError("connection failed"),
    ):
        result = await run_sherlockeye_osint("8.8.8.8")
    assert "Scan error" in result
    assert "Network error" in result
