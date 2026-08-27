# openosint/graph/export.py
"""
Phase 4 — streaming FtM entity export (.ftm-compatible newline-delimited JSON).

Only needs followthemoney (the `graph` extra) — no nomenklatura import, no
same_as clustering — so it works on Python 3.10+ without `graph-dedup`.
Streams one FtM entity dict per entity_id so a caller never needs the whole
graph in memory to export it; GraphStore.get_all_statements() is itself a
generator over the sqlite3 cursor for the same reason.
"""

from __future__ import annotations

from collections.abc import Iterator

from openosint.graph.entity_proxy import build_entity_proxy
from openosint.graph.materialize import breach_notes_for_statement
from openosint.graph.store.graph_store import GraphStore


def export_entities(
    store: GraphStore, *, exclude_datasets: frozenset[str] = frozenset()
) -> Iterator[dict]:
    """Yield one FtM entity dict (id, schema, properties) per entity_id in the store.

    exclude_datasets drops statements from those datasets BEFORE grouping —
    e.g. {"openosint:hibp"} removes every breach-sourced fact. If an entity
    ends up with zero surviving statements, it is not emitted at all; this
    is the mechanism that lets a caller fully omit breach data (or any other
    single source module's data) from an export.

    breach_name (sidecar-only — see provenance.py's module docstring) is
    materialized into a `notes` property value on the owning entity at
    export time, the one place this project turns sidecar-only data into a
    real FtM property (see materialize.py's module docstring for why: an
    exported entity has no sidecar to carry breach_name along otherwise).
    """
    statements_by_entity: dict[str, list] = {}
    for stmt in store.get_all_statements(exclude_datasets=exclude_datasets):
        statements_by_entity.setdefault(stmt.entity_id, []).append(stmt)

    for entity_id, stmts in statements_by_entity.items():
        proxy = build_entity_proxy(entity_id, stmts)
        notes = _breach_notes_for_entity(store, stmts)
        if notes and "notes" in proxy.schema.properties:
            proxy.add("notes", notes, cleaned=False)
        yield proxy.to_dict()


def _breach_notes_for_entity(store: GraphStore, stmts) -> str | None:
    records = [rec for stmt in stmts for rec in store.get_provenance(stmt.id)]
    return breach_notes_for_statement(records)
