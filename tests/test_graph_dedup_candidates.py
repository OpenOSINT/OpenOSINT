# tests/test_graph_dedup_candidates.py
"""Tests for openosint.graph.dedup.candidates — candidate-pair generation."""

from __future__ import annotations

import sys

import pytest

if sys.version_info < (3, 11):
    pytest.skip("requires Python >= 3.11 (graph-dedup extra)", allow_module_level=True)

from openosint.graph.dedup.candidates import (  # noqa: E402
    MATCHABLE_SCHEMAS,
    block_candidates,
    same_schema_pairs,
)


class TestSameSchemaPairs:
    def test_pairs_entities_of_the_same_schema(self):
        entities = [("a", "Person"), ("b", "Person"), ("c", "Person")]
        pairs = same_schema_pairs(entities)
        assert set(pairs) == {("a", "b"), ("a", "c"), ("b", "c")}

    def test_never_pairs_across_different_schemas(self):
        entities = [("a", "Person"), ("b", "Organization")]
        assert same_schema_pairs(entities) == []

    def test_never_pairs_a_schema_outside_matchable_schemas(self):
        entities = [("a", "Membership"), ("b", "Membership")]
        assert same_schema_pairs(entities) == []

    def test_single_entity_has_no_pairs(self):
        assert same_schema_pairs([("a", "Person")]) == []

    def test_matchable_schemas_matches_what_mapping_py_actually_emits(self):
        assert MATCHABLE_SCHEMAS == {"Person", "LegalEntity", "Organization", "UserAccount"}


class TestBlockCandidates:
    """The Phase 3 stub — see openosint/graph/dedup/candidates.py for the full contract."""

    def test_returns_a_subset_of_same_schema_pairs(self):
        entities = [("a", "Person"), ("b", "Person"), ("c", "Person")]
        expected_pairs = set(same_schema_pairs(entities))
        result = block_candidates(entities, max_pairs=2)
        assert set(result) <= expected_pairs

    def test_respects_the_max_pairs_budget(self):
        entities = [(f"e{i}", "Person") for i in range(50)]
        result = block_candidates(entities, max_pairs=10)
        assert len(result) <= 10
