# tests/test_graph_identity.py
"""Tests for openosint.graph.identity — deterministic, schema-scoped entity ids."""

from __future__ import annotations

import pytest

pytest.importorskip("followthemoney", reason="requires the 'graph' extra")


from openosint.graph.identity import entity_id_for  # noqa: E402


class TestEntityIdFor:
    def test_same_schema_and_parts_are_stable(self):
        first = entity_id_for("UserAccount", "github", "octocat")
        second = entity_id_for("UserAccount", "github", "octocat")
        assert first == second

    def test_different_schema_same_parts_do_not_collide(self):
        person_id = entity_id_for("Person", "github", "octocat")
        account_id = entity_id_for("UserAccount", "github", "octocat")
        assert person_id != account_id

    def test_different_key_parts_produce_different_ids(self):
        assert entity_id_for("LegalEntity", "example.com") != entity_id_for(
            "LegalEntity", "other.com"
        )

    def test_empty_key_parts_raise(self):
        with pytest.raises(ValueError):
            entity_id_for("LegalEntity")
