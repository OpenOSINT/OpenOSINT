# tests/test_graph_store_queries.py
"""Tests for GraphStore query methods: by entity, by schema, provenance history."""

from __future__ import annotations

from datetime import datetime, timezone

from openosint.correlation import EntityType, make_entity
from openosint.graph.identity import entity_id_for
from openosint.graph.mapping import map_github, map_whois
from openosint.graph.store import GraphStore

_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
_GITHUB_SEED = make_entity(EntityType.USERNAME, "octocat", 1.0)
_GITHUB_RAW = "[GitHub] Login: octocat\n[GitHub] Name: The Octocat\n[GitHub] Company: @GitHub\n"
_WHOIS_SEED = make_entity(EntityType.DOMAIN, "example.com", 1.0)
_WHOIS_RAW = "WHOIS results for 'example.com':\n\n[+] Org: Example Corp\n"


def _populated_store():
    store = GraphStore(":memory:")
    store.append(map_github(_GITHUB_RAW, _GITHUB_SEED, run_id="run-1", collected_at=_NOW))
    store.append(map_whois(_WHOIS_RAW, _WHOIS_SEED, run_id="run-1", collected_at=_NOW))
    return store


class TestGetStatementsByEntity:
    def test_returns_only_that_entitys_statements(self):
        store = _populated_store()
        account_id = entity_id_for("UserAccount", "github", "octocat")
        statements = store.get_statements_by_entity(account_id)
        assert statements
        assert all(s.entity_id == account_id for s in statements)
        store.close()

    def test_unknown_entity_returns_empty_list(self):
        store = _populated_store()
        assert store.get_statements_by_entity("does-not-exist") == []
        store.close()


class TestGetStatementsBySchema:
    def test_returns_only_matching_schema(self):
        store = _populated_store()
        rows = store.get_statements_by_schema("UserAccount")
        assert rows
        assert all(s.schema == "UserAccount" for s in rows)
        store.close()

    def test_different_schemas_do_not_leak_into_each_other(self):
        store = _populated_store()
        legal_entity_rows = store.get_statements_by_schema("LegalEntity")
        org_id = entity_id_for("Organization", "github-company", "github")
        assert not any(s.entity_id == org_id for s in legal_entity_rows)
        store.close()


class TestGetProvenance:
    def test_round_trips_extractor_confidence_and_method(self):
        store = _populated_store()
        account_id = entity_id_for("UserAccount", "github", "octocat")
        stmt = next(s for s in store.get_statements_by_entity(account_id) if s.prop == "username")
        prov = store.get_provenance(stmt.id)
        assert len(prov) == 1
        assert prov[0].collection_method == "map_github:username"
        assert 0.0 <= prov[0].extractor_confidence <= 1.0

    def test_unknown_statement_id_returns_empty_list(self):
        store = _populated_store()
        assert store.get_provenance("does-not-exist") == []
        store.close()
