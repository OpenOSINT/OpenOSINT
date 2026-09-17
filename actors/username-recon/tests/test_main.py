"""Unit tests for openosint-username-recon: validation and parsing only.

Network calls (sherlock) are always mocked — these tests never hit the
network or a real Actor run.
"""

from __future__ import annotations

import re
import time
from unittest.mock import AsyncMock, patch

import pytest

from src.main import (
    MAX_USERNAMES_PER_RUN,
    chunk_site_data,
    generate_control_username,
    scan_chunk,
    scan_username,
    validate_usernames,
)


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


class TestChunkSiteData:
    def test_splits_into_chunks_of_requested_size(self):
        site_data = {f"site{i}": {} for i in range(10)}
        chunks = chunk_site_data(site_data, size=4)
        assert [len(c) for c in chunks] == [4, 4, 2]

    def test_preserves_all_sites_across_chunks(self):
        site_data = {f"site{i}": {"info": i} for i in range(9)}
        chunks = chunk_site_data(site_data, size=4)
        merged = {}
        for c in chunks:
            merged.update(c)
        assert merged == site_data

    def test_empty_site_data_returns_no_chunks(self):
        assert chunk_site_data({}, size=40) == []

    def test_default_chunk_size_matches_constant(self):
        from src.main import _CHUNK_SIZE

        site_data = {f"site{i}": {} for i in range(_CHUNK_SIZE + 1)}
        chunks = chunk_site_data(site_data)
        assert len(chunks) == 2


class TestGenerateControlUsername:
    def test_looks_like_a_plausible_short_username(self):
        username = generate_control_username()
        assert re.fullmatch(r"[0-9a-f]{12}", username)

    def test_is_not_constant_across_calls(self):
        usernames = {generate_control_username() for _ in range(5)}
        assert len(usernames) > 1


class TestScanChunk:
    async def test_returns_hits_on_success(self):
        expected = [{"username": "alice", "platform": "GitHub", "url": "https://github.com/alice", "category": None}]
        with patch("src.main.run_username_osint_structured", new=AsyncMock(return_value=expected)):
            hits = await scan_chunk("alice", chunk={"GitHub": {}})
        assert hits == expected

    async def test_returns_none_without_raising_on_timeout(self):
        async def _hang(*_a, **_k):
            raise TimeoutError()

        with patch("src.main.run_username_osint_structured", new=_hang):
            result = await scan_chunk("alice", chunk={"GitHub": {}})
        assert result is None

    async def test_returns_none_without_raising_on_tool_error(self):
        from openosint.tools.exceptions import ToolExecutionError

        with patch(
            "src.main.run_username_osint_structured",
            new=AsyncMock(side_effect=ToolExecutionError("boom")),
        ):
            result = await scan_chunk("alice", chunk={"GitHub": {}})
        assert result is None


class TestScanUsername:
    async def test_aggregates_hits_across_successful_chunks(self):
        hits_a = [{"platform": "GitHub"}]
        hits_b = [{"platform": "Reddit"}]
        with patch("src.main.scan_chunk", new=AsyncMock(side_effect=[hits_a, hits_b])):
            hits, had_success = await scan_username("alice", chunks=[{"a": {}}, {"b": {}}], run_deadline=time.monotonic() + 60)
        assert hits == hits_a + hits_b
        assert had_success is True

    async def test_had_success_true_if_any_chunk_succeeds(self):
        with patch("src.main.scan_chunk", new=AsyncMock(side_effect=[None, [{"platform": "GitHub"}]])):
            hits, had_success = await scan_username("alice", chunks=[{"a": {}}, {"b": {}}], run_deadline=time.monotonic() + 60)
        assert had_success is True
        assert hits == [{"platform": "GitHub"}]

    async def test_had_success_false_when_every_chunk_fails(self):
        with patch("src.main.scan_chunk", new=AsyncMock(return_value=None)):
            hits, had_success = await scan_username("alice", chunks=[{"a": {}}, {"b": {}}], run_deadline=time.monotonic() + 60)
        assert had_success is False
        assert hits == []

    async def test_stops_early_once_run_deadline_has_passed(self):
        mock_chunk = AsyncMock(return_value=[{"platform": "GitHub"}])
        with patch("src.main.scan_chunk", new=mock_chunk):
            await scan_username("alice", chunks=[{"a": {}}, {"b": {}}, {"c": {}}], run_deadline=time.monotonic() - 1)
        mock_chunk.assert_not_called()


def test_max_usernames_per_run_matches_spec():
    assert MAX_USERNAMES_PER_RUN == 20
