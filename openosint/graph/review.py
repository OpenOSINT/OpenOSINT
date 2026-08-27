# openosint/graph/review.py
"""
Phase 4 — the human review queue for crossref-suggested same_as candidates.

WHY this must exist (blocking finding from the Phase 3 review): run_crossref
writes judgement='unsure' rows and canonical_for() only clusters over active
positive edges, so candidates correctly never auto-merge — but nothing let a
human ever SEE or DECIDE them. This module is that path. It reads/writes
plain resolutions rows through GraphStore and parses already-computed JSON
out of decided_by_detail; it never imports nomenklatura, so — unlike
openosint.graph.dedup — it works on Python 3.10 without the `graph-dedup`
extra. If crossref has never run in a given store, list_review_candidates()
simply returns an empty queue; there is nothing extra to gate.

decide_review_candidate() is the ONLY place outside a human's own judgement
that may write judgement='positive' — see openosint.graph.dedup's package
docstring for why the auto-scoring path is forbidden from ever doing that.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from openosint.graph.store.graph_store import GraphStore
from openosint.graph.store.resolutions import Resolution, make_resolution

# FtM schema.featured order first (the properties an analyst most wants to
# see first), then any other prop the entity happens to carry, alphabetically.
_FEATURED_PROPS: dict[str, tuple[str, ...]] = {
    "Person": ("name", "nationality", "birthDate"),
    "LegalEntity": ("name", "country", "legalForm", "status"),
    "Organization": ("name", "country", "legalForm", "status"),
    "UserAccount": ("username", "service", "email", "owner"),
}


@dataclass(frozen=True)
class PendingCandidate:
    """One 'unsure' pair awaiting human review, formatted for a reviewer to read."""

    resolution_id: int
    entity_id_a: str
    entity_id_b: str
    schema: str
    score: float | None
    explanation_text: str
    entity_a_properties: dict[str, list[str]]
    entity_b_properties: dict[str, list[str]]
    algorithm_name: str | None
    algorithm_version: str | None
    run_id: str | None


def list_review_candidates(
    store: GraphStore,
    *,
    schema: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    dataset: str | None = None,
) -> list[PendingCandidate]:
    """Pending 'unsure' candidates, sorted by score descending, with reviewer-facing detail.

    Filters (schema, min_score/max_score, dataset) are applied here, not in
    SQL — GraphStore.pending_resolutions() stays a dumb "give me every
    pending row" query; deciding what a schema/dataset filter even MEANS
    (an entity's dataset is the union of every statement's dataset, since a
    Person can carry facts from more than one source module) is a judgment
    this layer makes, not the store.

    A pair whose entities are gone from the store (e.g. erased since the
    candidate was suggested — requirement B) is silently skipped: there is
    nothing left to show a reviewer.
    """
    candidates: list[PendingCandidate] = []
    for resolution in store.pending_resolutions():
        if min_score is not None and (resolution.score is None or resolution.score < min_score):
            continue
        if max_score is not None and (resolution.score is None or resolution.score > max_score):
            continue

        stmts_a = store.get_statements_by_entity(resolution.entity_id)
        stmts_b = store.get_statements_by_entity(resolution.canonical_id)
        if not stmts_a or not stmts_b:
            continue

        entity_schema = stmts_a[0].schema
        if schema is not None and entity_schema != schema:
            continue

        datasets = {s.dataset for s in stmts_a} | {s.dataset for s in stmts_b}
        if dataset is not None and dataset not in datasets:
            continue

        detail = _parse_detail(resolution.decided_by_detail)
        algorithm = detail.get("algorithm") if isinstance(detail.get("algorithm"), dict) else {}
        candidates.append(
            PendingCandidate(
                resolution_id=resolution.id,
                entity_id_a=resolution.entity_id,
                entity_id_b=resolution.canonical_id,
                schema=entity_schema,
                score=resolution.score,
                explanation_text=_format_explanation(detail),
                entity_a_properties=_identifying_properties(entity_schema, stmts_a),
                entity_b_properties=_identifying_properties(entity_schema, stmts_b),
                algorithm_name=algorithm.get("name"),
                algorithm_version=algorithm.get("version"),
                run_id=detail.get("run_id"),
            )
        )

    candidates.sort(key=lambda c: (c.score is None, -(c.score or 0.0)))
    return candidates


def decide_review_candidate(
    store: GraphStore,
    *,
    entity_id: str,
    canonical_id: str,
    judgement: str,
    decided_at: datetime,
    reviewer_id: str | None = None,
) -> Resolution:
    """Record a human decision on one pair — always decided_by='human'.

    judgement='positive' (accept) is what run_crossref/scoring.py may never
    write on its own; judgement='negative' (reject) is what makes
    GraphStore.has_resolution() permanently skip this pair on every future
    crossref run (see resolutions.py's module docstring on undirected-edge
    semantics, and GraphStore.pending_resolutions()'s docstring). No
    resolutions column holds a reviewer id (decided_by is constrained to
    {'human', 'auto'}), so it is folded into decided_by_detail as JSON when
    given, kept out of it entirely otherwise.
    """
    detail = json.dumps({"reviewer_id": reviewer_id}, sort_keys=True) if reviewer_id else None
    resolution = make_resolution(
        entity_id=entity_id,
        canonical_id=canonical_id,
        judgement=judgement,
        decided_by="human",
        decided_at=decided_at,
        decided_by_detail=detail,
    )
    resolution_id = store.append_resolution(resolution)
    return Resolution(
        entity_id=resolution.entity_id,
        canonical_id=resolution.canonical_id,
        judgement=resolution.judgement,
        decided_by=resolution.decided_by,
        decided_at=resolution.decided_at,
        score=resolution.score,
        decided_by_detail=resolution.decided_by_detail,
        revokes_resolution_id=resolution.revokes_resolution_id,
        id=resolution_id,
    )


def prioritize_review_queue(
    candidates: Sequence[PendingCandidate], *, max_items: int
) -> list[PendingCandidate]:
    """Return a SMALLER, smarter review queue than list_review_candidates()'s plain score-descending order.

    WHY you should write this one by hand: score-descending is a correct,
    working default, but it is not obviously the most USEFUL order once a
    store has more pending candidates than one analyst reviews in a sitting.
    A better queue might prioritize pairs that would merge two previously
    isolated clusters (see GraphStore.connected_component) over pairs
    already inside the same cluster from another accepted merge, or
    diversity-sample across schema types so one noisy schema (say,
    UserAccount) doesn't crowd out every Person candidate, or weight recency
    so newly-discovered pairs surface before stale ones. That is a product
    judgment about analyst attention, not plumbing — the same kind of call
    already made by hand in openosint/graph/store/neighbors.py's
    rank_neighbors_for_truncation() and openosint/graph/dedup/candidates.py's
    block_candidates().

    Contract this must satisfy:
      - Every item returned must also be an item of *candidates* (never
        invent or drop identity — only reorder and subset).
      - len(result) <= max_items.
      - Pure function: same input -> same output, no I/O (the caller already
        fetched *candidates` via list_review_candidates()).

    To wire it in: graph_review_candidates' MCP handler calls
    list_review_candidates() then, only when the queue is large, passes the
    result through this function before formatting it for the reviewer.
    """
    raise NotImplementedError(
        "Phase 4 stub — see this function's docstring, then implement it and "
        "wire it into openosint.graph.mcp_tools.run_graph_review_candidates."
    )


def _identifying_properties(schema: str, statements: Sequence) -> dict[str, list[str]]:
    """Group *statements*' prop -> distinct values, FtM's featured props first."""
    values_by_prop: dict[str, list[str]] = {}
    for stmt in statements:
        bucket = values_by_prop.setdefault(stmt.prop, [])
        if stmt.value not in bucket:
            bucket.append(stmt.value)

    featured = _FEATURED_PROPS.get(schema, ())
    ordered_props = [p for p in featured if p in values_by_prop]
    ordered_props += sorted(p for p in values_by_prop if p not in featured)
    return {prop: values_by_prop[prop] for prop in ordered_props}


def _parse_detail(decided_by_detail: str | None) -> dict:
    if not decided_by_detail:
        return {}
    try:
        parsed = json.loads(decided_by_detail)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _format_explanation(detail: dict) -> str:
    """Turn a crossref decided_by_detail payload into a human-readable line, not raw JSON."""
    features = detail.get("features")
    if not isinstance(features, dict) or not features:
        return "No feature explanation recorded."

    ranked = sorted(
        features.items(),
        key=lambda item: (
            (item[1].get("score") is None, -(item[1].get("score") or 0.0))
            if isinstance(item[1], dict)
            else (True, 0.0)
        ),
    )
    lines = []
    for name, feature in ranked:
        if not isinstance(feature, dict):
            continue
        score = feature.get("score")
        score_text = f"{score:.2f}" if isinstance(score, (int, float)) else "?"
        query = feature.get("query")
        candidate = feature.get("candidate")
        compared = f" ('{query}' vs '{candidate}')" if query or candidate else ""
        lines.append(f"{name}={score_text}{compared}")
    return "; ".join(lines) if lines else "No feature explanation recorded."
