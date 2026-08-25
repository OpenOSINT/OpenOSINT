# tests/test_graph_names.py
"""Tests for openosint.graph.names — minimal, narrow-scope name extraction."""

from __future__ import annotations

from openosint.graph.names import extract_github_name, extract_whois_registrant_name


class TestExtractGithubName:
    def test_returns_the_name_field(self):
        raw = "[GitHub] Login: octocat\n[GitHub] Name: The Octocat\n[GitHub] Bio: N/A\n"
        assert extract_github_name(raw) == "The Octocat"

    def test_placeholder_na_returns_none(self):
        raw = "[GitHub] Login: octocat\n[GitHub] Name: N/A\n"
        assert extract_github_name(raw) is None

    def test_missing_line_returns_none(self):
        assert extract_github_name("[GitHub] Login: octocat\n") is None

    def test_empty_input_returns_none(self):
        assert extract_github_name("") is None

    def test_malformed_input_does_not_raise(self):
        assert extract_github_name("not even close to the expected format") is None


class TestExtractWhoisRegistrantName:
    """The Phase 1 stub — see openosint/graph/names.py for the full contract."""

    def test_extract_whois_registrant_name_returns_real_name(self):
        raw = (
            "WHOIS results for 'example.com':\n\n"
            "[+] Registrar: Example Registrar\n"
            "[+] Name: Jane Doe\n"
            "[+] Org: Example Corp\n"
        )
        assert extract_whois_registrant_name(raw) == "Jane Doe"

    def test_extract_whois_registrant_name_drops_privacy_masked_values(self):
        raw = "WHOIS results for 'example.com':\n\n[+] Name: REDACTED FOR PRIVACY\n"
        assert extract_whois_registrant_name(raw) is None

    def test_extract_whois_registrant_name_returns_none_when_absent(self):
        raw = "WHOIS results for 'example.com':\n\n[+] Registrar: Example Registrar\n"
        assert extract_whois_registrant_name(raw) is None
