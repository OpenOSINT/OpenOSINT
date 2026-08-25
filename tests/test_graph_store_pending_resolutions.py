# tests/test_graph_store_pending_resolutions.py
"""Tests for GraphStore.pending_resolutions() — the human review queue's source query."""

from __future__ import annotations

from datetime import datetime, timezone

from openosint.graph.store import GraphStore
from openosint.graph.store.resolutions import make_resolution

_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
_LATER = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)


def _append(store, a, b, judgement, *, decided_at=_NOW, decided_by="auto", score=None):
    store.append_resolution(
        make_resolution(
            entity_id=a,
            canonical_id=b,
            judgement=judgement,
            decided_by=decided_by,
            decided_at=decided_at,
            score=score,
        )
    )


class TestPendingResolutions:
    def test_an_unsure_row_is_pending(self):
        store = GraphStore(":memory:")
        _append(store, "a", "b", "unsure", score=0.7)
        pending = store.pending_resolutions()
        assert len(pending) == 1
        assert {pending[0].entity_id, pending[0].canonical_id} == {"a", "b"}
        store.close()

    def test_a_decided_pair_is_not_pending(self):
        store = GraphStore(":memory:")
        _append(store, "a", "b", "unsure", score=0.7)
        _append(store, "a", "b", "positive", decided_at=_LATER, decided_by="human")
        assert store.pending_resolutions() == []
        store.close()

    def test_a_rejected_pair_is_not_pending(self):
        store = GraphStore(":memory:")
        _append(store, "a", "b", "unsure", score=0.7)
        _append(store, "a", "b", "negative", decided_at=_LATER, decided_by="human")
        assert store.pending_resolutions() == []
        store.close()

    def test_only_unsure_pairs_are_returned_among_several(self):
        store = GraphStore(":memory:")
        _append(store, "a", "b", "unsure", score=0.9)
        _append(store, "c", "d", "positive", decided_by="human")
        _append(store, "e", "f", "unsure", score=0.6)
        pending = store.pending_resolutions()
        pairs = {frozenset((r.entity_id, r.canonical_id)) for r in pending}
        assert pairs == {frozenset({"a", "b"}), frozenset({"e", "f"})}
        store.close()
