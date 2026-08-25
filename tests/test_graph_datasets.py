# tests/test_graph_datasets.py
"""Tests for openosint.graph.datasets — one FtM dataset per source module."""

from __future__ import annotations

from openosint.graph.datasets import dataset_for_tool


class TestDatasetForTool:
    def test_default_rule_strips_search_prefix(self):
        assert dataset_for_tool("search_whois") == "openosint:whois"
        assert dataset_for_tool("search_github") == "openosint:github"
        assert dataset_for_tool("search_dns") == "openosint:dns"

    def test_breach_override_uses_hibp(self):
        assert dataset_for_tool("search_breach") == "openosint:hibp"

    def test_distinct_tools_get_distinct_datasets(self):
        assert dataset_for_tool("search_whois") != dataset_for_tool("search_github")
