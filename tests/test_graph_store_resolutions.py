# tests/test_graph_store_resolutions.py
"""Tests for GraphStore resolutions — requirement A, cluster (connected-components) semantics.

Revoking a merge means appending a new row for the SAME PAIR of entities
with a non-positive judgement — never a self-referencing row (make_resolution
rejects entity_id == canonical_id outright; see resolutions.py).
"""

from __future__ import annotations

import pytest

pytest.importorskip("followthemoney", reason="requires the 'graph' extra")

from datetime import datetime, timezone  # noqa: E402

from openosint.graph.store import GraphStore  # noqa: E402
from openosint.graph.store.resolutions import make_resolution  # noqa: E402

_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
_LATER = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)


def _merge(store, a, b, *, decided_at=_NOW, decided_by="auto", score=0.9):
    store.append_resolution(
        make_resolution(
            entity_id=a,
            canonical_id=b,
            judgement="positive",
            decided_by=decided_by,
            decided_at=decided_at,
            score=score,
        )
    )


def _revoke(store, a, b, *, decided_at):
    """Undo a merge by appending a new row for the SAME pair, not a self-loop."""
    store.append_resolution(
        make_resolution(
            entity_id=a,
            canonical_id=b,
            judgement="no_judgement",
            decided_by="human",
            decided_at=decided_at,
        )
    )


class TestSingleEdge:
    def test_unresolved_entity_is_its_own_canonical(self):
        store = GraphStore(":memory:")
        assert store.canonical_for("entity-a") == "entity-a"
        store.close()

    def test_positive_judgement_makes_the_max_of_the_pair_canonical(self):
        store = GraphStore(":memory:")
        _merge(store, "a", "b")
        assert store.canonical_for("a") == store.canonical_for("b") == "b"
        store.close()

    def test_negative_judgement_does_not_link_the_pair(self):
        store = GraphStore(":memory:")
        store.append_resolution(
            make_resolution(
                entity_id="a",
                canonical_id="b",
                judgement="negative",
                decided_by="human",
                decided_at=_NOW,
            )
        )
        assert store.canonical_for("a") == "a"
        assert store.canonical_for("b") == "b"
        store.close()


class TestTransitiveClustering:
    """Required: A<->B, B<->C => canonical_for(A) == canonical_for(C), no direct A<->C row."""

    def test_transitive_chain_resolves_to_one_shared_canonical(self):
        store = GraphStore(":memory:")
        _merge(store, "a", "b")
        _merge(store, "b", "c")
        assert store.canonical_for("a") == store.canonical_for("b") == store.canonical_for("c")
        assert store.canonical_for("a") == "c"  # max("a", "b", "c")
        store.close()

    def test_members_of_canonical_returns_the_whole_transitive_cluster(self):
        store = GraphStore(":memory:")
        _merge(store, "a", "b")
        _merge(store, "b", "c")
        assert store.members_of_canonical("c") == ["a", "b", "c"]
        store.close()


class TestRevokeWithRedundantPathIntact:
    """Required: revoking B<->C where A<->C also exists => cluster stays intact."""

    def test_cluster_survives_because_a_different_edge_still_connects_it(self):
        store = GraphStore(":memory:")
        _merge(store, "a", "b")
        _merge(store, "b", "c")
        _merge(store, "a", "c")
        assert store.canonical_for("a") == "c"

        _revoke(store, "b", "c", decided_at=_LATER)

        # b is still reachable from a (a<->b), and a<->c is untouched, so the
        # whole component {a, b, c} remains connected.
        assert store.connected_component("a") == {"a", "b", "c"}
        assert store.canonical_for("a") == store.canonical_for("b") == store.canonical_for("c")
        assert store.canonical_for("a") == "c"
        store.close()


class TestRevokeMiddleOfChainSplits:
    """Required: revoking the middle edge of a chain => cluster splits into two."""

    def test_four_node_chain_splits_at_the_revoked_middle_edge(self):
        store = GraphStore(":memory:")
        _merge(store, "a", "b")
        _merge(store, "b", "c")  # the middle edge of the a-b-c-d chain
        _merge(store, "c", "d")
        assert store.connected_component("a") == {"a", "b", "c", "d"}

        _revoke(store, "b", "c", decided_at=_LATER)

        assert store.connected_component("a") == {"a", "b"}
        assert store.connected_component("d") == {"c", "d"}
        assert store.canonical_for("a") == store.canonical_for("b") == "b"
        assert store.canonical_for("c") == store.canonical_for("d") == "d"
        store.close()


class TestErasingClusterMember:
    """Required: erasing one member of a 3-way cluster => the other two keep their existing
    canonical, no silent reshaping."""

    def test_erasing_a_member_with_a_redundant_edge_leaves_the_survivors_clustered(self):
        store = GraphStore(":memory:")
        _merge(store, "a", "b")
        _merge(store, "b", "c")
        _merge(store, "a", "c")
        assert store.canonical_for("a") == store.canonical_for("c") == "c"

        store.erase("b", request_id="req-1")

        # a and c had their OWN direct edge — erasing b (and the two edges
        # that mention it) must not disturb the a<->c relationship at all.
        assert store.canonical_for("a") == "c"
        assert store.canonical_for("c") == "c"
        store.close()

    def test_erasing_the_hub_of_a_chain_with_no_redundant_edge_dissolves_to_singletons(self):
        store = GraphStore(":memory:")
        _merge(store, "a", "b")
        _merge(store, "b", "c")
        assert store.canonical_for("a") == "c"

        store.erase("b", request_id="req-2")

        # No direct a<->c edge ever existed — erasing the only bridge must
        # NOT silently invent a new a<->c relationship. Both revert to being
        # their own canonical.
        assert store.canonical_for("a") == "a"
        assert store.canonical_for("c") == "c"
        store.close()


class TestResolutionValidation:
    def test_self_referencing_row_is_rejected(self):
        with pytest.raises(ValueError):
            make_resolution(
                entity_id="a",
                canonical_id="a",
                judgement="positive",
                decided_by="human",
                decided_at=_NOW,
            )

    def test_invalid_judgement_raises(self):
        with pytest.raises(ValueError):
            make_resolution(
                entity_id="a",
                canonical_id="b",
                judgement="definitely",
                decided_by="human",
                decided_at=_NOW,
            )

    def test_invalid_decided_by_raises(self):
        with pytest.raises(ValueError):
            make_resolution(
                entity_id="a",
                canonical_id="b",
                judgement="positive",
                decided_by="robot",
                decided_at=_NOW,
            )

    def test_score_out_of_range_raises(self):
        with pytest.raises(ValueError):
            make_resolution(
                entity_id="a",
                canonical_id="b",
                judgement="positive",
                decided_by="auto",
                decided_at=_NOW,
                score=1.2,
            )
