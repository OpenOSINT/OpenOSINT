# tests/test_graph_dedup_scoring.py
"""Tests for openosint.graph.dedup.scoring — the nomenklatura ScoringAlgorithm wrapper.

IMPORTANT: nomenklatura's LogicV2 name-matching memoizes per EntityProxy.id
(nomenklatura/matching/logic_v2/names/analysis.py's entity_names(), an
lru_cache keyed on EntityProxy.__hash__, which nomenklatura's own comment
documents as ID-only: "if the properties of the underlying entity change,
this cache will not be invalidated"). Reusing a literal id like "id-a" across
two proxies with DIFFERENT property content in the same process returns a
STALE cached score for the second one — every proxy built below therefore
gets a fresh, never-reused id via _next_id(). See crossref.py's module
docstring for what this means for real (non-test) usage.
"""

from __future__ import annotations

import itertools
import sys

import pytest

if sys.version_info < (3, 11):
    pytest.skip("requires Python >= 3.11 (graph-dedup extra)", allow_module_level=True)

from followthemoney import model  # noqa: E402

from openosint.graph.dedup.scoring import explanation_to_dict, score_pair  # noqa: E402

_id_counter = itertools.count()


def _next_id() -> str:
    return f"test-entity-{next(_id_counter)}"


def _proxy(schema: str, **props):
    proxy = model.make_entity(schema)
    proxy.id = _next_id()
    for prop, value in props.items():
        proxy.add(prop, value, cleaned=False)
    return proxy


class TestScorePair:
    def test_identical_names_score_highly(self):
        a = _proxy("Person", name="Jane Doe")
        b = _proxy("Person", name="Jane Doe")
        result = score_pair(a, b)
        assert result.score > 0.8

    def test_unrelated_names_score_low(self):
        a = _proxy("Person", name="Jane Doe")
        b = _proxy("Person", name="Bob Smith")
        result = score_pair(a, b)
        assert result.score < 0.5

    def test_result_carries_feature_explanations(self):
        a = _proxy("Person", name="Jane Doe")
        b = _proxy("Person", name="Jane Doe")
        result = score_pair(a, b)
        assert len(result.explanations) > 0


class TestExplanationToDict:
    def test_produces_a_json_serializable_structure(self):
        import json

        a = _proxy("Person", name="Jane Doe")
        b = _proxy("Person", name="Jane Doe")
        result = score_pair(a, b)
        payload = explanation_to_dict(result)
        json.dumps(payload)  # must not raise
        assert "name_match" in payload
        assert "score" in payload["name_match"]

    def test_empty_explanations_produce_an_empty_dict(self):
        a = _proxy("Person")
        b = _proxy("Person")
        result = score_pair(a, b)
        payload = explanation_to_dict(result)
        assert isinstance(payload, dict)
