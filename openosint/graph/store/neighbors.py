# openosint/graph/store/neighbors.py
"""
Pure data shapes and ranking policy for GraphStore.neighbors().

Kept separate from graph_store.py (which does the actual SQL/BFS) so the one
genuinely open design question here — HOW to prioritize which neighbors
survive a fan-out cap — is a small, pure, independently testable seam rather
than buried inside I/O code.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from openosint.graph.bridge import BridgeLink


@dataclass(frozen=True)
class NeighborCandidate:
    """One candidate neighbor discovered during BFS, before any fan-out cap is applied."""

    entity_id: str
    prop: str
    direction: str  # "outgoing" | "incoming"


@dataclass(frozen=True)
class NeighborResult:
    """The result of one GraphStore.neighbors() call.

    bridge_links is only populated when the caller passed cross_layer=True —
    it surfaces the DIRECT bridge edges for every FtM entity reached during
    BFS (Q1's "traverse the bridge"), not a recursive walk into the infra
    EntityGraph itself: that graph is never persisted (it only exists
    transiently during one pivot.py run), so there is nothing further to
    traverse into past the bridge edge.
    """

    entities: tuple[str, ...]
    edges: tuple[tuple[str, str, str], ...]  # (source_entity_id, target_entity_id, prop)
    bridge_links: tuple[BridgeLink, ...]
    truncated: bool


def rank_neighbors_for_truncation(
    candidates: Sequence[NeighborCandidate],
) -> list[NeighborCandidate]:
    """Order one node's neighbor candidates so a fan-out cap keeps the MOST USEFUL ones first.

    WHY you should write this one by hand: GraphStore.neighbors() today caps
    a high-degree node's neighbors by `ORDER BY value` in SQL — deterministic,
    but arbitrary from an analyst's point of view. A hub with 500 connections
    capped at 50 should probably keep the ones an investigator would actually
    want to see first — maybe the ones backed by the highest
    extractor_confidence, maybe the most recently observed, maybe a
    prop-specific priority (an `owner` link likely matters more than a
    `member` link). That's a product judgment call about what makes an OSINT
    graph useful, not a plumbing one, and it deserves your judgment rather
    than mine.

    Contract this must satisfy (see the failing test in
    tests/test_graph_store_neighbors.py::TestRankNeighborsForTruncation):
      - Return a list containing every candidate in *candidates*, reordered
        (never dropped — the caller applies the fan-out cap after ranking).
      - Must be a pure function: same input -> same output, no I/O.

    To wire it in once implemented: replace GraphStore._fanout_cap()'s
    `ORDER BY value` cap with a call to this function on the fetched
    candidates before slicing to fanout_cap. Doing that will likely mean
    fetching extractor_confidence alongside each candidate (a join against
    `provenance`) — that plumbing change is part of wiring this in, not part
    of writing this function.
    """
    raise NotImplementedError(
        "Phase 2 stub — see this function's docstring, then implement it and "
        "un-skip tests/test_graph_store_neighbors.py::TestRankNeighborsForTruncation."
    )
