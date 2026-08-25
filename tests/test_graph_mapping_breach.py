# tests/test_graph_mapping_breach.py
"""Tests for openosint.graph.mapping.map_breach.

Correction 1: a breach is provenance, not a `notes` string. N breaches found
must yield ONE Statement (the email property) and N ProvenanceRecords, each
carrying its own breach_name — never a per-breach `notes` statement.
"""

from __future__ import annotations

from datetime import datetime, timezone

from followthemoney.statement import Statement

from openosint.correlation import EntityType, make_entity
from openosint.graph.datasets import dataset_for_tool
from openosint.graph.identity import entity_id_for
from openosint.graph.mapping import map_breach

_SEED = make_entity(EntityType.EMAIL, "jane@example.com", 1.0)
_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
_OWNER_ID = entity_id_for("LegalEntity", "email-owner", "jane@example.com")

_ONE_BREACH_RAW = (
    "Found in 1 breach(es) for 'jane@example.com':\n\n"
    "[+] Adobe (2013-10-04) — leaked: Emails, Passwords\n"
)
_TWO_BREACHES_RAW = (
    "Found in 2 breach(es) for 'jane@example.com':\n\n"
    "[+] Adobe (2013-10-04) — leaked: Emails, Passwords\n"
    "[+] LinkedIn (2012-05-05) — leaked: Emails\n"
)


class TestMapBreachNoSyntheticEntity:
    def test_no_notes_or_organization_statement_is_ever_emitted(self):
        result = map_breach(_ONE_BREACH_RAW, _SEED, run_id="run-1", collected_at=_NOW)
        assert not any(s.prop == "notes" for s in result.statements)
        assert not any(s.schema == "Organization" for s in result.statements)
        assert all(s.entity_id == _OWNER_ID for s in result.statements)

    def test_dataset_is_hibp(self):
        result = map_breach(_ONE_BREACH_RAW, _SEED, run_id="run-1", collected_at=_NOW)
        assert all(s.dataset == "openosint:hibp" for s in result.statements)
        assert all(s.dataset == dataset_for_tool("search_breach") for s in result.statements)


class TestMapBreachStatementSidecarShape:
    """The core correction-1 case: N breaches -> ONE statement + N provenance records."""

    def test_one_breach_yields_one_statement_and_one_provenance_record(self):
        result = map_breach(_ONE_BREACH_RAW, _SEED, run_id="run-1", collected_at=_NOW)
        assert len(result.statements) == 1
        assert result.statements[0].prop == "email"
        assert result.statements[0].value == "jane@example.com"
        assert len(result.provenance) == 1
        assert result.provenance[0].breach_name == "Adobe"

    def test_two_breaches_yield_one_statement_and_two_provenance_records(self):
        result = map_breach(_TWO_BREACHES_RAW, _SEED, run_id="run-1", collected_at=_NOW)
        assert len(result.statements) == 1  # not two — same email statement, re-observed
        assert len(result.provenance) == 2
        breach_names = {p.breach_name for p in result.provenance}
        assert breach_names == {"Adobe", "LinkedIn"}
        assert all(p.statement_id == result.statements[0].id for p in result.provenance)

    def test_bridge_link_points_back_to_seed_email(self):
        result = map_breach(_ONE_BREACH_RAW, _SEED, run_id="run-1", collected_at=_NOW)
        assert len(result.bridge_links) == 1
        link = result.bridge_links[0]
        assert link.ftm_entity_id == _OWNER_ID
        assert link.graph_entity_type == EntityType.EMAIL


class TestMapBreachMalformedInput:
    def test_no_breaches_found_returns_empty_result(self):
        result = map_breach(
            "No breaches found for 'jane@example.com'.", _SEED, run_id="run-1", collected_at=_NOW
        )
        assert result.statements == ()
        assert result.provenance == ()

    def test_empty_raw_returns_empty_result(self):
        result = map_breach("", _SEED, run_id="run-1", collected_at=_NOW)
        assert result.statements == ()


class TestStatementDatasetScopingAcrossSources:
    """Direct proof of the Q3 mechanism: same entity/prop/value in two datasets both survive."""

    def test_same_property_value_in_two_datasets_yields_two_statement_ids(self):
        common_kwargs = dict(
            entity_id=_OWNER_ID, prop="email", schema="LegalEntity", value="jane@example.com"
        )
        from_hibp = Statement(**common_kwargs, dataset="openosint:hibp")
        from_whois = Statement(**common_kwargs, dataset="openosint:whois")
        assert from_hibp.id != from_whois.id
        combined = [from_hibp, from_whois]
        assert len({s.id for s in combined}) == 2
