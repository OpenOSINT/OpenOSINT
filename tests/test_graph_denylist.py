# tests/test_graph_denylist.py
"""Tests for openosint.graph.denylist — WHOIS privacy-proxy placeholder filtering."""

from __future__ import annotations

from openosint.graph.denylist import is_privacy_masked


class TestIsPrivacyMasked:
    def test_exact_match_is_masked(self):
        assert is_privacy_masked("REDACTED FOR PRIVACY") is True

    def test_case_and_punctuation_variants_are_masked(self):
        assert is_privacy_masked("Redacted-For-Privacy!!") is True
        assert is_privacy_masked("redacted for privacy") is True

    def test_registrar_suffix_still_matches_via_substring(self):
        assert is_privacy_masked("Whois Privacy Protection Service, Inc.") is True

    def test_domains_by_proxy_variants(self):
        assert is_privacy_masked("Domains By Proxy, LLC") is True
        assert is_privacy_masked("DomainsByProxy.com") is True

    def test_real_org_name_is_not_masked(self):
        assert is_privacy_masked("Example Corp") is False
        assert is_privacy_masked("Jane Doe") is False

    def test_empty_or_whitespace_is_not_masked(self):
        assert is_privacy_masked("") is False
        assert is_privacy_masked("   ") is False

    def test_malformed_input_does_not_raise(self):
        assert is_privacy_masked("!!!@@@###") is False
