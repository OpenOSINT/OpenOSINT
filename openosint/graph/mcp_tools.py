# openosint/graph/mcp_tools.py
"""
Phase 4 — MCP tool implementations for the graph module.

Each function here mirrors the openosint/tools/search_*.py convention: an
async run_*_osint-style coroutine returning a human-readable text report, so
it plugs into mcp_server.py's existing Tool/_HANDLERS/to_json machinery with
no special formatting logic on that side. GraphStore access is synchronous
(sqlite3) — wrapped in asyncio.to_thread(), the same pattern
openosint/tools/search_whois.py uses for its own blocking call (see
graph_store.py's own module docstring, which predicted exactly this).

Importing this module pulls in followthemoney (openosint.graph.store ->
openosint.graph.mapping -> followthemoney.statement). mcp_server.py imports
it lazily, INSIDE the dispatch function, wrapped in try/except ImportError —
never at module top level — so a missing `graph` extra degrades to a clear
per-call error message instead of breaking every other, unrelated MCP tool
at server startup. graph_export and graph_neighbors need nothing beyond
that. graph_review_candidates reads resolutions rows a prior graph-dedup
crossref pass produced but never imports nomenklatura itself, so it also
works on Python 3.10 without the `graph-dedup` extra — it just reports an
empty queue if crossref has never run in this store.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

# Leaf module — imports only os/pathlib, never followthemoney — so importing it
# here does not violate this module's "no heavy imports at top level" contract.
from openosint.graph.store.db_path import default_db_path


async def run_graph_export(*, exclude_datasets: list[str] | None = None) -> str:
    """Export the graph store as newline-delimited FtM entity JSON, one entity per line."""

    def _work() -> str:
        from openosint.graph.export import export_entities
        from openosint.graph.store import GraphStore

        store = GraphStore(default_db_path())
        try:
            lines = [
                json.dumps(entity, sort_keys=True)
                for entity in export_entities(
                    store, exclude_datasets=frozenset(exclude_datasets or [])
                )
            ]
        finally:
            store.close()
        return "\n".join(lines) if lines else "No entities in the graph store to export."

    return await asyncio.to_thread(_work)


async def run_graph_neighbors(entity_id: str, *, depth: int = 1, cross_layer: bool = False) -> str:
    """Traverse the graph from *entity_id* out to *depth* hops, with per-edge provenance."""

    def _work() -> str:
        from openosint.graph.store import GraphStore

        store = GraphStore(default_db_path())
        try:
            result = store.neighbors(entity_id, depth=depth, cross_layer=cross_layer)
            if not result.entities:
                return f"No neighbors found for {entity_id} within depth {depth}."

            lines = [f"Neighbors of {entity_id} (depth {depth}):", ""]
            lines.append(f"Entities ({len(result.entities)}): " + ", ".join(result.entities))
            lines.append("")
            lines.append("Edges:")
            for source, target, prop in result.edges:
                lines.append(
                    f"  {source} --[{prop}]--> {target}"
                    f"{_provenance_suffix(store, source, prop, target)}"
                )

            if cross_layer:
                lines.append("")
                if result.bridge_links:
                    lines.append("Bridge links (cross-layer, into the raw infra graph):")
                    for link in result.bridge_links:
                        lines.append(
                            f"  {link.ftm_entity_id} --[{link.relation}]--> "
                            f"{link.graph_entity_type.value}:{link.graph_entity_normalized}"
                        )
                else:
                    lines.append("No bridge links found for the entities in this subgraph.")

            if result.truncated:
                lines.append("")
                lines.append(
                    "NOTE: one or more nodes exceeded the fan-out cap; some neighbors were omitted."
                )
            return "\n".join(lines)
        finally:
            store.close()

    return await asyncio.to_thread(_work)


def _provenance_suffix(store, source: str, prop: str, target: str) -> str:
    stmt = next(
        (s for s in store.get_statements_by_entity(source) if s.prop == prop and s.value == target),
        None,
    )
    if stmt is None:
        return ""
    records = store.get_provenance(stmt.id)
    if not records:
        return ""
    latest = records[-1]
    return (
        f" (via {latest.collection_method}, confidence={latest.extractor_confidence}, "
        f"run={latest.run_id})"
    )


async def run_graph_review_candidates(
    action: str,
    *,
    schema: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    dataset: str | None = None,
    entity_id: str | None = None,
    canonical_id: str | None = None,
    decision: str | None = None,
    reviewer_id: str | None = None,
) -> str:
    """action='list' shows the pending human-review queue; action='decide' records a verdict."""

    def _work() -> str:
        from openosint.graph.review import decide_review_candidate, list_review_candidates
        from openosint.graph.store import GraphStore

        store = GraphStore(default_db_path())
        try:
            if action == "list":
                candidates = list_review_candidates(
                    store,
                    schema=schema,
                    min_score=min_score,
                    max_score=max_score,
                    dataset=dataset,
                )
                return _format_candidates(candidates)

            if action == "decide":
                if not entity_id or not canonical_id or decision not in ("accept", "reject"):
                    raise ValueError(
                        "action='decide' requires entity_id, canonical_id, and decision "
                        "('accept' or 'reject')."
                    )
                judgement = "positive" if decision == "accept" else "negative"
                resolution = decide_review_candidate(
                    store,
                    entity_id=entity_id,
                    canonical_id=canonical_id,
                    judgement=judgement,
                    decided_at=datetime.now(timezone.utc),
                    reviewer_id=reviewer_id,
                )
                return (
                    f"Recorded human {decision} for {entity_id} <-> {canonical_id} "
                    f"(resolution id {resolution.id}, judgement={judgement})."
                )

            raise ValueError(f"Unknown action {action!r}; expected 'list' or 'decide'.")
        finally:
            store.close()

    return await asyncio.to_thread(_work)


def _format_candidates(candidates) -> str:
    if not candidates:
        return "No pending review candidates."
    lines = [f"{len(candidates)} pending candidate(s), sorted by score descending:", ""]
    for c in candidates:
        score_text = f"{c.score:.3f}" if c.score is not None else "?"
        lines.append(f"[{c.resolution_id}] {c.schema} — score {score_text}")
        lines.append(f"  A ({c.entity_id_a}): {_props_line(c.entity_a_properties)}")
        lines.append(f"  B ({c.entity_id_b}): {_props_line(c.entity_b_properties)}")
        lines.append(f"  Why: {c.explanation_text}")
        if c.algorithm_name:
            lines.append(f"  Algorithm: {c.algorithm_name} v{c.algorithm_version or '?'}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _props_line(props: dict[str, list[str]]) -> str:
    if not props:
        return "(no properties)"
    return "; ".join(f"{k}={'/'.join(v)}" for k, v in props.items())
