# openosint/graph/store/__init__.py
"""
Phase 2 — the append-only SQLite store.

Unlike openosint/graph/{mapping,provenance,identity,...}.py (Phase 1, pure,
no I/O), everything under this package performs real file I/O and is
intentionally synchronous — sqlite3 is stdlib-synchronous and fast enough for
local single-file access. Callers on the async side (a future MCP tool in
Phase 4) wrap calls in asyncio.to_thread(), the same pattern search_whois.py
already uses for its own blocking call.
"""

from openosint.graph.store.graph_store import GraphStore
from openosint.graph.store.neighbors import (
    NeighborCandidate,
    NeighborResult,
    rank_neighbors_for_truncation,
)
from openosint.graph.store.resolutions import Resolution, make_resolution
from openosint.graph.store.tombstone import ErasureTombstone

__all__ = [
    "ErasureTombstone",
    "GraphStore",
    "NeighborCandidate",
    "NeighborResult",
    "Resolution",
    "make_resolution",
    "rank_neighbors_for_truncation",
]
