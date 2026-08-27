# tests/test_graph_store_neighbors.py
"""Tests for GraphStore.neighbors() — depth cap, cycle guard, fan-out cap, cross_layer."""

from __future__ import annotations

import pytest

pytest.importorskip("followthemoney", reason="requires the 'graph' extra")

from datetime import datetime, timezone  # noqa: E402

from followthemoney.statement import Statement  # noqa: E402

from openosint.graph.mapping import EmissionResult  # noqa: E402
from openosint.graph.store import GraphStore  # noqa: E402
from openosint.graph.store.neighbors import (  # noqa: E402
    NeighborCandidate,
    rank_neighbors_for_truncation,
)

_DATASET = "openosint:test"
_NOW_ISO = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc).isoformat()


def _stmt(entity_id: str, prop: str, schema: str, value: str) -> Statement:
    """UserAccount.owner is an entity-typed property — safe to reuse for synthetic edges."""
    return Statement(
        entity_id=entity_id,
        prop=prop,
        schema=schema,
        value=value,
        dataset=_DATASET,
        first_seen=_NOW_ISO,
        last_seen=_NOW_ISO,
    )


def _append_edge(store: GraphStore, source: str, target: str) -> None:
    stmt = _stmt(source, "owner", "UserAccount", target)
    store.append(EmissionResult(statements=(stmt,), provenance=(), bridge_links=()))


class TestNeighborsBasic:
    def test_finds_direct_outgoing_and_incoming_neighbors(self):
        store = GraphStore(":memory:")
        _append_edge(store, "account-1", "person-1")  # account-1 --owner--> person-1
        result = store.neighbors("person-1", depth=1)
        assert result.entities == ("account-1",)
        assert result.edges == (("account-1", "person-1", "owner"),)
        store.close()

    def test_non_entity_typed_property_is_not_treated_as_an_edge(self):
        store = GraphStore(":memory:")
        stmt = _stmt(
            "account-1", "username", "UserAccount", "octocat"
        )  # `username` is a string, not entity
        store.append(EmissionResult(statements=(stmt,), provenance=(), bridge_links=()))
        result = store.neighbors("account-1", depth=1)
        assert result.entities == ()
        store.close()

    def test_unknown_entity_has_no_neighbors(self):
        store = GraphStore(":memory:")
        result = store.neighbors("does-not-exist", depth=2)
        assert result.entities == ()
        assert result.edges == ()
        store.close()


class TestNeighborsCycle:
    def test_a_two_node_cycle_terminates_instead_of_looping(self):
        store = GraphStore(":memory:")
        _append_edge(store, "node-a", "node-b")
        _append_edge(store, "node-b", "node-a")
        result = store.neighbors("node-a", depth=5)  # would loop forever without a cycle guard
        assert result.entities == ("node-b",)
        store.close()

    def test_a_longer_cycle_is_fully_explored_exactly_once(self):
        store = GraphStore(":memory:")
        _append_edge(store, "a", "b")
        _append_edge(store, "b", "c")
        _append_edge(store, "c", "a")
        result = store.neighbors("a", depth=5)
        assert set(result.entities) == {"b", "c"}
        store.close()


class TestNeighborsDepthCap:
    def test_depth_beyond_the_hard_ceiling_is_clamped(self):
        store = GraphStore(":memory:")
        chain = ["n0", "n1", "n2", "n3", "n4", "n5", "n6", "n7"]
        for src, tgt in zip(chain, chain[1:]):
            _append_edge(store, src, tgt)
        result = store.neighbors("n0", depth=999)  # way past _MAX_DEPTH_CEILING
        assert "n7" not in result.entities  # unreachable within the hard ceiling
        store.close()

    def test_depth_zero_returns_no_neighbors(self):
        store = GraphStore(":memory:")
        _append_edge(store, "a", "b")
        result = store.neighbors("a", depth=0)
        assert result.entities == ()
        store.close()


class TestNeighborsFanoutCap:
    def test_high_degree_node_is_capped_and_flagged_truncated(self):
        store = GraphStore(":memory:")
        for i in range(100):
            _append_edge(store, f"account-{i}", "hub-person")
        result = store.neighbors("hub-person", depth=1, fanout_cap=50)
        assert result.truncated is True
        assert len(result.entities) == 50
        store.close()

    def test_degree_within_cap_is_not_flagged_truncated(self):
        store = GraphStore(":memory:")
        for i in range(10):
            _append_edge(store, f"account-{i}", "hub-person")
        result = store.neighbors("hub-person", depth=1, fanout_cap=50)
        assert result.truncated is False
        assert len(result.entities) == 10
        store.close()


class TestNeighborsCrossLayer:
    def test_cross_layer_false_returns_no_bridge_links(self):
        store = GraphStore(":memory:")
        result = store.neighbors("account-1", depth=1, cross_layer=False)
        assert result.bridge_links == ()
        store.close()

    def test_cross_layer_true_surfaces_bridge_links_for_the_seed(self):
        from openosint.correlation import EntityType
        from openosint.graph.bridge import BridgeLink

        store = GraphStore(":memory:")
        link = BridgeLink(
            ftm_entity_id="account-1",
            graph_entity_type=EntityType.USERNAME,
            graph_entity_normalized="octocat",
            relation="derived_from",
        )
        store.append(EmissionResult(statements=(), provenance=(), bridge_links=(link,)))
        result = store.neighbors("account-1", depth=1, cross_layer=True)
        assert len(result.bridge_links) == 1
        assert result.bridge_links[0].graph_entity_normalized == "octocat"
        store.close()


class TestRankNeighborsForTruncation:
    """The Phase 2 stub — see openosint/graph/store/neighbors.py for the full contract."""

    def test_returns_every_candidate_none_dropped(self):
        candidates = [
            NeighborCandidate(entity_id="a", prop="owner", direction="outgoing"),
            NeighborCandidate(entity_id="b", prop="member", direction="incoming"),
        ]
        ranked = rank_neighbors_for_truncation(candidates)
        assert set(ranked) == set(candidates)

    def test_empty_input_returns_empty_output(self):
        assert rank_neighbors_for_truncation([]) == []
