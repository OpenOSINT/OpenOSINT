# tests/test_json_export.py
"""
Tests for the JSON export functionality (--json flag / json_output parameter).

These tests verify that format_tool_result() and to_json() produce valid,
schema-conforming output for every tool name — without making real network
or subprocess calls.
"""

from __future__ import annotations

import json

import pytest

from openosint.json_output import format_tool_result, to_json

ALL_TOOLS = [
    "search_email",
    "search_username",
    "search_breach",
    "search_whois",
    "search_ip",
    "search_domain",
    "generate_dorks",
    "search_paste",
    "search_phone",
    "search_shodan",
    "search_virustotal",
    "search_sherlockeye",
]


# ---------------------------------------------------------------------------
# format_tool_result
# ---------------------------------------------------------------------------


class TestFormatToolResult:
    def test_required_keys_present(self):
        result = format_tool_result("search_email", "test@example.com", "some output")
        assert set(result.keys()) == {"tool", "target", "timestamp", "results", "error"}

    def test_tool_name_preserved(self):
        result = format_tool_result("search_ip", "8.8.8.8", "IP intelligence")
        assert result["tool"] == "search_ip"

    def test_target_preserved(self):
        result = format_tool_result("search_email", "test@example.com", "output")
        assert result["target"] == "test@example.com"

    def test_results_is_list(self):
        result = format_tool_result("search_email", "test@example.com", "line one\nline two")
        assert isinstance(result["results"], list)

    def test_results_splits_lines(self):
        result = format_tool_result("search_email", "t@e.com", "line one\nline two\nline three")
        assert len(result["results"]) == 3

    def test_results_filters_blank_lines(self):
        result = format_tool_result("search_email", "t@e.com", "line one\n\n\nline two")
        assert len(result["results"]) == 2

    def test_results_empty_on_empty_output(self):
        result = format_tool_result("search_email", "t@e.com", "")
        assert result["results"] == []

    def test_error_none_by_default(self):
        result = format_tool_result("search_breach", "t@e.com", "No breaches found")
        assert result["error"] is None

    def test_error_set_when_provided(self):
        result = format_tool_result("search_email", "t@e.com", "", error="HIBP key missing")
        assert result["error"] == "HIBP key missing"

    def test_timestamp_is_string(self):
        result = format_tool_result("search_ip", "1.1.1.1", "some output")
        assert isinstance(result["timestamp"], str)
        assert len(result["timestamp"]) > 0

    def test_timestamp_is_iso8601(self):
        from datetime import datetime

        result = format_tool_result("search_ip", "1.1.1.1", "output")
        # Should not raise
        datetime.fromisoformat(result["timestamp"])


# ---------------------------------------------------------------------------
# to_json
# ---------------------------------------------------------------------------


class TestToJson:
    def test_returns_valid_json_string(self):
        json_str = to_json("search_breach", "test@example.com", "No breaches found")
        # Should not raise
        data = json.loads(json_str)
        assert isinstance(data, dict)

    def test_json_matches_format_tool_result_schema(self):
        json_str = to_json("search_whois", "example.com", "WHOIS data here")
        data = json.loads(json_str)
        assert set(data.keys()) == {"tool", "target", "timestamp", "results", "error"}

    def test_json_error_field(self):
        json_str = to_json("search_email", "t@e.com", "", error="tool not found")
        data = json.loads(json_str)
        assert data["error"] == "tool not found"


# ---------------------------------------------------------------------------
# Parametrize over all 9 tool names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", ALL_TOOLS)
def test_each_tool_produces_valid_json_schema(tool_name):
    """Every tool name must produce a valid, schema-conforming JSON result."""
    sample_result = f"Sample output for {tool_name}"
    result = format_tool_result(tool_name, "test_target", sample_result)

    assert result["tool"] == tool_name
    assert result["target"] == "test_target"
    assert isinstance(result["results"], list)
    assert result["error"] is None
    # Must be JSON-serialisable
    serialised = json.dumps(result)
    reparsed = json.loads(serialised)
    assert reparsed["tool"] == tool_name


@pytest.mark.parametrize("tool_name", ALL_TOOLS)
def test_each_tool_to_json_is_valid(tool_name):
    """to_json() must return parseable JSON for every tool name."""
    json_str = to_json(tool_name, "target_value", "Result line 1\nResult line 2")
    data = json.loads(json_str)
    assert data["tool"] == tool_name
    assert len(data["results"]) == 2
