"""Unit tests for openosint-username-recon: validation and parsing only.

Network calls (sherlock) are always mocked — these tests never hit the
network or a real Actor run.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.main import MAX_USERNAMES_PER_RUN, scan_with_retry, validate_usernames


class TestValidateUsernames:
    def test_accepts_well_formed_usernames(self):
        valid, rejected = validate_usernames(["johndoe", "octo-cat", "user.name_1"])
        assert valid == ["johndoe", "octo-cat", "user.name_1"]
        assert rejected == []

    def test_rejects_malformed_usernames(self):
        valid, rejected = validate_usernames(["ok_user", "has space", "semi;colon", ""])
        assert valid == ["ok_user"]
        assert "has space" in rejected
        assert "semi;colon" in rejected

    def test_dedupes_preserving_first_occurrence_order(self):
        valid, rejected = validate_usernames(["alice", "bob", "alice", " bob "])
        assert valid == ["alice", "bob"]
        assert rejected == []

    def test_coerces_non_string_items(self):
        valid, rejected = validate_usernames([12345])
        assert valid == ["12345"]
        assert rejected == []


class TestScanWithRetry:
    async def test_returns_hits_on_success(self):
        expected = [{"username": "alice", "platform": "GitHub", "url": "https://github.com/alice", "category": None}]
        with patch("src.main.run_username_osint_structured", new=AsyncMock(return_value=expected)):
            hits = await scan_with_retry("alice", site_data={})
        assert hits == expected

    async def test_retries_then_succeeds(self):
        from openosint.tools.exceptions import ToolExecutionError

        mock_scan = AsyncMock(side_effect=[ToolExecutionError("boom"), []])
        with patch("src.main.run_username_osint_structured", new=mock_scan), patch("src.main._RETRY_BACKOFF_SECONDS", 0):
            hits = await scan_with_retry("alice", site_data={})
        assert hits == []
        assert mock_scan.call_count == 2

    async def test_gives_up_after_max_attempts_without_raising(self):
        from openosint.tools.exceptions import ToolExecutionError

        mock_scan = AsyncMock(side_effect=ToolExecutionError("still down"))
        with patch("src.main.run_username_osint_structured", new=mock_scan), patch("src.main._RETRY_BACKOFF_SECONDS", 0):
            hits = await scan_with_retry("alice", site_data={})
        assert hits == []


def test_max_usernames_per_run_matches_spec():
    assert MAX_USERNAMES_PER_RUN == 20
