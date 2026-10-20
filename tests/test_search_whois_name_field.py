# tests/test_search_whois_name_field.py
"""Covers the Phase 1 addition to search_whois.py: the registrant Name field.

Kept as its own small file rather than added to tests/test_tools.py's
TestSearchWhoisFormatting, so this Phase 1 change stays independently
reviewable from the pre-existing WHOIS formatting tests.
"""

from __future__ import annotations

from openosint.tools.search_whois import _format_whois_results


class TestWhoisNameField:
    def test_registrant_name_is_included_when_present(self):
        class FakeWhois:
            domain_name = "EXAMPLE.COM"
            registrar = "Example Registrar"
            creation_date = None
            expiration_date = None
            updated_date = None
            name_servers = None
            emails = None
            name = "Jane Doe"
            org = None
            country = None

        result = _format_whois_results(FakeWhois(), "example.com")
        assert "[+] Name: Jane Doe" in result

    def test_absent_name_attribute_omits_the_line(self):
        class FakeWhois:
            domain_name = "EXAMPLE.COM"
            registrar = "Example Registrar"
            creation_date = None
            expiration_date = None
            updated_date = None
            name_servers = None
            emails = None
            org = None
            country = None

        result = _format_whois_results(FakeWhois(), "example.com")
        assert "[+] Name:" not in result
