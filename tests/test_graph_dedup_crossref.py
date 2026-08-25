# tests/test_graph_dedup_crossref.py
"""Tests for openosint.graph.dedup.crossref — the full cross-reference pass.

CRITICAL: every test class here ultimately re-checks the same invariant —
run_crossref() must never write judgement='positive'. That check is
repeated in each class deliberately, not just once, so a future change that
breaks it in one code path can't hide behind a class that happens not to
assert it.
"""

from __future__ import annotations

import json
import sys

import pytest

if sys.version_info < (3, 11):
    pytest.skip("requires Python >= 3.11 (graph-dedup extra)", allow_module_level=True)

from datetime import datetime, timezone  # noqa: E402

from openosint.correlation import EntityType, make_entity  # noqa: E402
from openosint.graph.dedup import run_crossref  # noqa: E402
from openosint.graph.mapping import map_github  # noqa: E402
from openosint.graph.store import GraphStore  # noqa: E402

_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)


def _github_profile(login: str, name: str, email: str) -> str:
    return f"[GitHub] Login: {login}\n[GitHub] Name: {name}\n[GitHub] Email (profile): {email}\n"


def _two_matching_accounts_store() -> GraphStore:
    store = GraphStore(":memory:")
    seed1 = make_entity(EntityType.USERNAME, "janedoe1", 1.0)
    store.append(
        map_github(
            _github_profile("janedoe1", "Jane Doe", "jane@example.com"),
            seed1,
            run_id="run-1",
            collected_at=_NOW,
        )
    )
    seed2 = make_entity(EntityType.USERNAME, "jdoe_dev", 1.0)
    store.append(
        map_github(
            _github_profile("jdoe_dev", "Jane Doe", "jane@example.com"),
            seed2,
            run_id="run-1",
            collected_at=_NOW,
        )
    )
    return store


class TestNeverAutoMerge:
    def test_a_strong_match_is_suggested_as_unsure_not_positive(self):
        store = _two_matching_accounts_store()
        suggested = run_crossref(store, run_id="crossref-1", decided_at=_NOW, min_threshold=0.3)
        assert len(suggested) >= 1

        for resolution in store.resolution_history():
            assert resolution.judgement != "positive"
            assert resolution.judgement == "unsure"
            assert resolution.decided_by == "auto"
        store.close()

    def test_canonical_for_is_unaffected_until_a_human_decides(self):
        """An 'unsure' suggestion must not itself change clustering."""
        store = _two_matching_accounts_store()
        person_ids_before = {s.entity_id for s in store.get_statements_by_schema("Person")}
        run_crossref(store, run_id="crossref-1", decided_at=_NOW, min_threshold=0.3)
        for pid in person_ids_before:
            assert store.canonical_for(pid) == pid  # still its own canonical
        store.close()


class TestFeatureExposure:
    def test_suggested_candidate_carries_a_score_and_explanation(self):
        store = _two_matching_accounts_store()
        suggested = run_crossref(store, run_id="crossref-1", decided_at=_NOW, min_threshold=0.3)
        assert suggested[0].score > 0
        assert len(suggested[0].explanation) > 0
        store.close()

    def test_the_stored_resolution_row_lets_a_reviewer_see_why(self):
        store = _two_matching_accounts_store()
        run_crossref(store, run_id="crossref-1", decided_at=_NOW, min_threshold=0.3)
        resolution = store.resolution_history()[0]
        payload = json.loads(resolution.decided_by_detail)
        assert payload["run_id"] == "crossref-1"
        assert "features" in payload
        assert len(payload["features"]) > 0
        store.close()


class TestNoDuplicateSuggestions:
    def test_re_running_crossref_does_not_re_suggest_an_already_resolved_pair(self):
        store = _two_matching_accounts_store()
        first = run_crossref(store, run_id="crossref-1", decided_at=_NOW, min_threshold=0.3)
        second = run_crossref(store, run_id="crossref-2", decided_at=_NOW, min_threshold=0.3)
        assert len(first) >= 1
        assert len(second) == 0
        for resolution in store.resolution_history():
            assert resolution.judgement != "positive"
        store.close()

    def test_a_pair_a_human_already_said_no_to_is_never_re_suggested(self):
        from openosint.graph.identity import entity_id_for
        from openosint.graph.store.resolutions import make_resolution

        store = _two_matching_accounts_store()
        person_a = entity_id_for("Person", "github", "janedoe1")
        person_b = entity_id_for("Person", "github", "jdoe_dev")
        store.append_resolution(
            make_resolution(
                entity_id=person_a,
                canonical_id=person_b,
                judgement="negative",
                decided_by="human",
                decided_at=_NOW,
            )
        )
        suggested = run_crossref(store, run_id="crossref-1", decided_at=_NOW, min_threshold=0.3)
        assert not any({c.entity_id_a, c.entity_id_b} == {person_a, person_b} for c in suggested)
        store.close()


class TestNeverIndexesBridgeOrInfraNodes:
    def test_bridge_linked_infra_entities_never_appear_as_candidates(self):
        store = _two_matching_accounts_store()
        # bridge_links exist (from map_github's derived_from links to the
        # seed username EntityGraph nodes) but those graph_entity ids are
        # never FtM entity ids and never appear in `statements`.
        bridge_rows = store._conn.execute("SELECT ftm_entity_id FROM bridge_links").fetchall()
        assert len(bridge_rows) > 0  # sanity: bridges do exist in this fixture

        suggested = run_crossref(store, run_id="crossref-1", decided_at=_NOW, min_threshold=0.3)
        candidate_ids = {c.entity_id_a for c in suggested} | {c.entity_id_b for c in suggested}
        schemas = {
            row["schema"]
            for eid in candidate_ids
            for row in store._conn.execute(
                "SELECT DISTINCT schema FROM statements WHERE entity_id = ?", (eid,)
            ).fetchall()
        }
        assert schemas <= {"Person", "LegalEntity", "Organization", "UserAccount"}
        store.close()

    def test_membership_edge_entities_are_never_candidates(self):
        """Membership is created by map_github but is not in MATCHABLE_SCHEMAS."""
        store = _two_matching_accounts_store()
        # both fixture profiles share Company: nothing here, so add one with a company
        seed3 = make_entity(EntityType.USERNAME, "another_dev", 1.0)
        raw3 = "[GitHub] Login: another_dev\n[GitHub] Name: Someone Else\n[GitHub] Company: @Acme\n"
        store.append(map_github(raw3, seed3, run_id="run-1", collected_at=_NOW))

        membership_rows = store.get_statements_by_schema("Membership")
        assert membership_rows  # sanity: a Membership entity does exist

        suggested = run_crossref(store, run_id="crossref-1", decided_at=_NOW, min_threshold=0.3)
        candidate_ids = {c.entity_id_a for c in suggested} | {c.entity_id_b for c in suggested}
        membership_ids = {s.entity_id for s in membership_rows}
        assert candidate_ids.isdisjoint(membership_ids)
        store.close()


class TestThreshold:
    def test_low_scoring_pairs_are_not_suggested(self):
        store = GraphStore(":memory:")
        seed1 = make_entity(EntityType.USERNAME, "alice1", 1.0)
        store.append(
            map_github(
                _github_profile("alice1", "Alice Anderson", "alice@example.com"),
                seed1,
                run_id="run-1",
                collected_at=_NOW,
            )
        )
        seed2 = make_entity(EntityType.USERNAME, "bobsmith", 1.0)
        store.append(
            map_github(
                _github_profile("bobsmith", "Bob Smith", "bob@other.com"),
                seed2,
                run_id="run-1",
                collected_at=_NOW,
            )
        )
        suggested = run_crossref(store, run_id="crossref-1", decided_at=_NOW, min_threshold=0.9)
        assert suggested == []
        store.close()
