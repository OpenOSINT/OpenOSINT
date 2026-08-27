# tests/test_graph_mapping_whois.py
"""Tests for openosint.graph.mapping.map_whois."""

from __future__ import annotations

import pytest

pytest.importorskip("followthemoney", reason="requires the 'graph' extra")

from datetime import datetime, timezone  # noqa: E402

from openosint.correlation import EntityType, make_entity  # noqa: E402
from openosint.graph.identity import entity_id_for  # noqa: E402
from openosint.graph.mapping import map_whois  # noqa: E402

_SEED = make_entity(EntityType.DOMAIN, "example.com", 1.0)
_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
_REGISTRANT_ID = entity_id_for("LegalEntity", "whois-registrant", "example.com")


def _prop_values(result, entity_id, prop):
    return [s.value for s in result.statements if s.entity_id == entity_id and s.prop == prop]


class TestMapWhoisIdentityFields:
    def test_email_and_org_become_registrant_properties(self):
        raw = (
            "WHOIS results for 'example.com':\n\n"
            "[+] Emails: admin@example.com\n"
            "[+] Org: Example Corp\n"
            "[+] Name Servers: ns1.example.com, ns2.example.com\n"
        )
        result = map_whois(raw, _SEED, run_id="run-1", collected_at=_NOW)
        assert _prop_values(result, _REGISTRANT_ID, "email") == ["admin@example.com"]
        assert _prop_values(result, _REGISTRANT_ID, "name") == ["Example Corp"]

    def test_nameservers_are_never_mapped(self):
        raw = (
            "WHOIS results for 'example.com':\n\n"
            "[+] Org: Example Corp\n"
            "[+] Name Servers: ns1.example.com, ns2.example.com\n"
        )
        result = map_whois(raw, _SEED, run_id="run-1", collected_at=_NOW)
        assert not any("ns1.example.com" in s.value for s in result.statements)

    def test_domain_itself_never_becomes_an_entity(self):
        raw = "WHOIS results for 'example.com':\n\n[+] Org: Example Corp\n"
        result = map_whois(raw, _SEED, run_id="run-1", collected_at=_NOW)
        assert all(s.entity_id != "example.com" for s in result.statements)

    def test_bridge_link_points_back_to_seed_domain(self):
        raw = "WHOIS results for 'example.com':\n\n[+] Org: Example Corp\n"
        result = map_whois(raw, _SEED, run_id="run-1", collected_at=_NOW)
        assert len(result.bridge_links) == 1
        link = result.bridge_links[0]
        assert link.ftm_entity_id == _REGISTRANT_ID
        assert link.graph_entity_type == EntityType.DOMAIN
        assert link.graph_entity_normalized == "example.com"


class TestMapWhoisPrivacyDenylist:
    def test_privacy_masked_org_is_dropped_not_emitted(self):
        raw = "WHOIS results for 'example.com':\n\n[+] Org: REDACTED FOR PRIVACY\n"
        result = map_whois(raw, _SEED, run_id="run-1", collected_at=_NOW)
        assert result.statements == ()

    def test_masked_org_alongside_real_email_keeps_only_the_email(self):
        raw = (
            "WHOIS results for 'example.com':\n\n"
            "[+] Emails: admin@example.com\n"
            "[+] Org: Domains By Proxy, LLC\n"
        )
        result = map_whois(raw, _SEED, run_id="run-1", collected_at=_NOW)
        assert _prop_values(result, _REGISTRANT_ID, "email") == ["admin@example.com"]
        assert _prop_values(result, _REGISTRANT_ID, "name") == []


class TestMapWhoisMissingFields:
    def test_no_identity_fields_at_all_returns_empty_result(self):
        raw = "WHOIS results for 'example.com':\n\n[+] Registrar: Example Registrar\n"
        result = map_whois(raw, _SEED, run_id="run-1", collected_at=_NOW)
        assert result.statements == ()
        assert result.bridge_links == ()


class TestMapWhoisMalformedInput:
    def test_empty_raw_returns_empty_result(self):
        result = map_whois("", _SEED, run_id="run-1", collected_at=_NOW)
        assert result.statements == ()

    def test_no_whois_data_message_returns_empty_result(self):
        result = map_whois(
            "No WHOIS data found for 'unknown.xyz'.", _SEED, run_id="run-1", collected_at=_NOW
        )
        assert result.statements == ()
