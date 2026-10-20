# openosint/graph/entity_proxy.py
"""
Convert stored Statements into a FtM EntityProxy.

Lives directly under openosint.graph, NOT under openosint.graph.dedup — this
adapter only needs followthemoney (the `graph` extra), never nomenklatura, so
it must stay reachable on Python 3.10 without the `graph-dedup` extra.
openosint.graph.dedup (Phase 3's nomenklatura scoring) imports and reuses it
for the same purpose; Phase 4's graph_export/graph_neighbors MCP tools import
it directly, which is exactly why it moved out of the gated package — it was
misplaced there, not nomenklatura-specific. Pure: takes already-fetched
statements, does no I/O itself.
"""

from __future__ import annotations

from collections.abc import Sequence

from followthemoney import model
from followthemoney.proxy import EntityProxy
from followthemoney.statement import Statement


def build_entity_proxy(entity_id: str, statements: Sequence[Statement]) -> EntityProxy:
    """Build one EntityProxy from all of *entity_id*'s statements.

    Raises
    ------
    ValueError
        If *statements* is empty (an EntityProxy needs a schema, and schema
        is only known from at least one statement) or the statements disagree
        about which schema *entity_id* belongs to (they must not — every
        map_* function in mapping.py assigns one fixed schema per entity id).
    """
    if not statements:
        raise ValueError(f"cannot build an EntityProxy for {entity_id!r} with no statements")
    schemas = {s.schema for s in statements}
    if len(schemas) > 1:
        raise ValueError(f"entity {entity_id!r} has conflicting schemas: {sorted(schemas)}")

    proxy = model.make_entity(schemas.pop())
    proxy.id = entity_id
    for stmt in statements:
        proxy.add(stmt.prop, stmt.value, cleaned=False)
    return proxy
