# tests/test_graph_review.py
"""Tests for openosint.graph.review — the human review path (Phase 4, item 1 & 2).

No Python 3.11 / nomenklatura guard on most of this file: list_review_candidates
and decide_review_candidate only read/write plain resolutions rows and never
import nomenklatura. The end-to-end TestRejectionNeverResurfaces class DOES
need run_crossref (real Phase 3 scoring) and is guarded accordingly.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from followthemoney.statement import Statement

from openosint.graph.mapping import EmissionResult
from openosint.graph.review import (
    PendingCandidate,
    decide_review_candidate,
    list_review_candidates,
)
from openosint.graph.store import GraphStore
from openosint.graph.store.resolutions import make_resolution

_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
_ISO = _NOW.isoformat()


def _emit(store, entity_id, schema, dataset, **props):
    statements = tuple(
        Statement(
            entity_id=entity_id,
            prop=prop,
            schema=schema,
            value=value,
            dataset=dataset,
            first_seen=_ISO,
            last_seen=_ISO,
        )
        for prop, value in props.items()
    )
    store.append(EmissionResult(statements=statements, provenance=(), bridge_links=()))


def _unsure(store, a, b, *, score=0.8, features=None, algorithm=None, run_id="crossref-1"):
    payload = {
        "run_id": run_id,
        "features": features or {"name_match": {"score": score, "query": "X", "candidate": "Y"}},
    }
    if algorithm:
        payload["algorithm"] = algorithm
    store.append_resolution(
        make_resolution(
            entity_id=a,
            canonical_id=b,
            judgement="unsure",
            decided_by="auto",
            decided_at=_NOW,
            score=score,
            decided_by_detail=json.dumps(payload),
        )
    )


class TestListReviewCandidates:
    def test_pending_pair_is_returned_with_identifying_properties(self):
        store = GraphStore(":memory:")
        _emit(store, "p-a", "Person", "openosint:github", name="Jane Doe")
        _emit(store, "p-b", "Person", "openosint:github", name="Jane A. Doe")
        _unsure(store, "p-a", "p-b", score=0.91)

        candidates = list_review_candidates(store)
        assert len(candidates) == 1
        c = candidates[0]
        assert isinstance(c, PendingCandidate)
        assert c.schema == "Person"
        assert c.score == 0.91
        assert c.entity_a_properties["name"] == ["Jane Doe"]
        assert c.entity_b_properties["name"] == ["Jane A. Doe"]
        store.close()

    def test_explanation_is_human_readable_not_raw_json(self):
        store = GraphStore(":memory:")
        _emit(store, "p-a", "Person", "openosint:github", name="Jane Doe")
        _emit(store, "p-b", "Person", "openosint:github", name="Jane Doe")
        _unsure(store, "p-a", "p-b", score=0.95)

        candidates = list_review_candidates(store)
        text = candidates[0].explanation_text
        assert "{" not in text  # not raw JSON
        assert "name_match" in text
        store.close()

    def test_sorted_by_score_descending(self):
        store = GraphStore(":memory:")
        _emit(store, "p-a", "Person", "d", name="A")
        _emit(store, "p-b", "Person", "d", name="B")
        _emit(store, "p-c", "Person", "d", name="C")
        _emit(store, "p-d", "Person", "d", name="D")
        _unsure(store, "p-a", "p-b", score=0.5)
        _unsure(store, "p-c", "p-d", score=0.9)

        scores = [c.score for c in list_review_candidates(store)]
        assert scores == [0.9, 0.5]
        store.close()

    def test_algorithm_identity_is_surfaced(self):
        store = GraphStore(":memory:")
        _emit(store, "p-a", "Person", "d", name="A")
        _emit(store, "p-b", "Person", "d", name="A")
        _unsure(store, "p-a", "p-b", algorithm={"name": "logic-v2", "version": "4.14.0"})

        c = list_review_candidates(store)[0]
        assert c.algorithm_name == "logic-v2"
        assert c.algorithm_version == "4.14.0"
        store.close()


class TestFilters:
    def test_filter_by_schema(self):
        store = GraphStore(":memory:")
        _emit(store, "p-a", "Person", "d", name="A")
        _emit(store, "p-b", "Person", "d", name="A")
        _emit(store, "o-a", "Organization", "d", name="Acme")
        _emit(store, "o-b", "Organization", "d", name="Acme")
        _unsure(store, "p-a", "p-b", score=0.8)
        _unsure(store, "o-a", "o-b", score=0.8)

        person_only = list_review_candidates(store, schema="Person")
        assert len(person_only) == 1
        assert person_only[0].schema == "Person"
        store.close()

    def test_filter_by_score_range(self):
        store = GraphStore(":memory:")
        _emit(store, "p-a", "Person", "d", name="A")
        _emit(store, "p-b", "Person", "d", name="A")
        _emit(store, "p-c", "Person", "d", name="A")
        _emit(store, "p-d", "Person", "d", name="A")
        _unsure(store, "p-a", "p-b", score=0.4)
        _unsure(store, "p-c", "p-d", score=0.9)

        mid_range = list_review_candidates(store, min_score=0.6, max_score=1.0)
        assert len(mid_range) == 1
        assert mid_range[0].score == 0.9
        store.close()

    def test_filter_by_dataset(self):
        store = GraphStore(":memory:")
        _emit(store, "p-a", "Person", "openosint:github", name="A")
        _emit(store, "p-b", "Person", "openosint:github", name="A")
        _emit(store, "p-c", "Person", "openosint:whois", name="B")
        _emit(store, "p-d", "Person", "openosint:whois", name="B")
        _unsure(store, "p-a", "p-b", score=0.8)
        _unsure(store, "p-c", "p-d", score=0.8)

        github_only = list_review_candidates(store, dataset="openosint:github")
        assert len(github_only) == 1
        assert {github_only[0].entity_id_a, github_only[0].entity_id_b} == {"p-a", "p-b"}
        store.close()


class TestDecideReviewCandidate:
    def test_accept_writes_positive_decided_by_human(self):
        store = GraphStore(":memory:")
        resolution = decide_review_candidate(
            store, entity_id="a", canonical_id="b", judgement="positive", decided_at=_NOW
        )
        assert resolution.judgement == "positive"
        assert resolution.decided_by == "human"
        assert store.canonical_for("a") == "b"
        store.close()

    def test_reject_writes_negative_decided_by_human(self):
        store = GraphStore(":memory:")
        resolution = decide_review_candidate(
            store, entity_id="a", canonical_id="b", judgement="negative", decided_at=_NOW
        )
        assert resolution.judgement == "negative"
        assert resolution.decided_by == "human"
        assert store.canonical_for("a") == "a"  # never merged
        store.close()

    def test_reviewer_id_is_recorded_when_given(self):
        store = GraphStore(":memory:")
        resolution = decide_review_candidate(
            store,
            entity_id="a",
            canonical_id="b",
            judgement="negative",
            decided_at=_NOW,
            reviewer_id="tommy",
        )
        detail = json.loads(resolution.decided_by_detail)
        assert detail["reviewer_id"] == "tommy"
        store.close()

    def test_decided_pair_drops_out_of_pending_list(self):
        store = GraphStore(":memory:")
        _emit(store, "p-a", "Person", "d", name="A")
        _emit(store, "p-b", "Person", "d", name="A")
        _unsure(store, "p-a", "p-b", score=0.8)
        assert len(list_review_candidates(store)) == 1

        decide_review_candidate(
            store, entity_id="p-a", canonical_id="p-b", judgement="negative", decided_at=_NOW
        )
        assert list_review_candidates(store) == []
        store.close()


if sys.version_info >= (3, 11):

    class TestRejectionNeverResurfaces:
        """End-to-end: reject a real crossref suggestion, re-run crossref, assert it's gone."""

        def test_a_rejected_pair_never_reappears_after_another_crossref_run(self):
            from openosint.correlation import EntityType, make_entity
            from openosint.graph.dedup import run_crossref
            from openosint.graph.identity import entity_id_for
            from openosint.graph.mapping import map_github

            store = GraphStore(":memory:")

            def profile(login, name, email):
                return (
                    f"[GitHub] Login: {login}\n[GitHub] Name: {name}\n"
                    f"[GitHub] Email (profile): {email}\n"
                )

            store.append(
                map_github(
                    profile("janedoe1", "Jane Doe", "jane@example.com"),
                    make_entity(EntityType.USERNAME, "janedoe1", 1.0),
                    run_id="run-1",
                    collected_at=_NOW,
                )
            )
            store.append(
                map_github(
                    profile("jdoe_dev", "Jane Doe", "jane@example.com"),
                    make_entity(EntityType.USERNAME, "jdoe_dev", 1.0),
                    run_id="run-1",
                    collected_at=_NOW,
                )
            )
            suggested = run_crossref(store, run_id="crossref-1", decided_at=_NOW, min_threshold=0.3)
            assert len(suggested) >= 1
            assert len(list_review_candidates(store)) >= 1

            person_a = entity_id_for("Person", "github", "janedoe1")
            person_b = entity_id_for("Person", "github", "jdoe_dev")
            decide_review_candidate(
                store,
                entity_id=person_a,
                canonical_id=person_b,
                judgement="negative",
                decided_at=_NOW,
            )
            assert list_review_candidates(store) == []

            second = run_crossref(store, run_id="crossref-2", decided_at=_NOW, min_threshold=0.3)
            assert not any({c.entity_id_a, c.entity_id_b} == {person_a, person_b} for c in second)
            assert list_review_candidates(store) == []
            store.close()
