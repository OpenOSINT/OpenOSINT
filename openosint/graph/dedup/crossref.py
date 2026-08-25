# openosint/graph/dedup/crossref.py
"""
Orchestrates one cross-reference pass: score candidate pairs, suggest matches.

The only I/O in this package — reads entities from GraphStore, writes
'unsure'/'auto' resolutions back. Never writes judgement='positive'; see the
package __init__.py docstring for why that line is drawn here, not left to
caller discipline.

CAVEAT: see scoring.py's module docstring for a real, discovered-not-guessed
limitation — nomenklatura's name-match cache is keyed by entity id alone, so
re-running run_crossref() in the same long-lived process after an entity's
statements changed can score it against stale, cached name analysis.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from openosint.graph.dedup.candidates import MATCHABLE_SCHEMAS, same_schema_pairs
from openosint.graph.dedup.scoring import (
    DEFAULT_ALGORITHM,
    DEFAULT_CROSSREF_THRESHOLD,
    algorithm_identity,
    clear_stale_name_cache,
    explanation_to_dict,
    score_pair,
)
from openosint.graph.entity_proxy import build_entity_proxy
from openosint.graph.store.graph_store import GraphStore
from openosint.graph.store.resolutions import make_resolution


@dataclass(frozen=True)
class CrossrefCandidate:
    """One scored pair this crossref pass suggested (or would have, above threshold)."""

    entity_id_a: str
    entity_id_b: str
    score: float
    explanation: dict[str, dict[str, object]]
    resolution_id: int


def run_crossref(
    store: GraphStore,
    *,
    run_id: str,
    decided_at: datetime,
    min_threshold: float = DEFAULT_CROSSREF_THRESHOLD,
    algorithm=DEFAULT_ALGORITHM,
    candidate_fn: Callable[[Sequence[tuple[str, str]]], list[tuple[str, str]]] = same_schema_pairs,
) -> list[CrossrefCandidate]:
    """Score every candidate pair among the store's matchable entities; suggest matches.

    For every pair scoring >= min_threshold that doesn't already have a
    resolution row (positive, negative, or a prior unsure suggestion — see
    GraphStore.has_resolution), appends ONE resolutions row with
    judgement='unsure', decided_by='auto', score=<the computed score>, and
    decided_by_detail holding a JSON explanation (plus run_id, for audit —
    resolutions has no dedicated run_id column, unlike provenance, and
    algorithm name/version — see scoring.algorithm_identity, so an old score
    stays interpretable after a nomenklatura upgrade) of which features drove
    it. NEVER writes judgement='positive' — see this package's __init__.py.

    Only entities whose schema is in MATCHABLE_SCHEMAS are ever fetched or
    compared (Person, LegalEntity, Organization, UserAccount) — bridge/infra
    nodes never have these schemas in `statements.schema` (Q1), so they are
    structurally excluded, not filtered after the fact.

    Calls scoring.clear_stale_name_cache() before scoring anything — see that
    function's docstring for the nomenklatura lru_cache bug it mitigates:
    without this, a second run_crossref() call in the same long-lived process
    could score a previously-seen entity against a stale, pre-update name
    analysis.
    """
    clear_stale_name_cache()

    entities: list[tuple[str, str]] = []
    statements_by_entity: dict[str, list] = {}
    for schema in MATCHABLE_SCHEMAS:
        for stmt in store.get_statements_by_schema(schema):
            statements_by_entity.setdefault(stmt.entity_id, []).append(stmt)
    for entity_id, stmts in statements_by_entity.items():
        entities.append((entity_id, stmts[0].schema))

    pairs = candidate_fn(entities)

    proxy_cache: dict[str, object] = {}

    def _proxy(entity_id: str):
        if entity_id not in proxy_cache:
            proxy_cache[entity_id] = build_entity_proxy(entity_id, statements_by_entity[entity_id])
        return proxy_cache[entity_id]

    suggested: list[CrossrefCandidate] = []
    for entity_id_a, entity_id_b in pairs:
        if store.has_resolution(entity_id_a, entity_id_b):
            continue

        result = score_pair(_proxy(entity_id_a), _proxy(entity_id_b), algorithm=algorithm)
        if result.score < min_threshold:
            continue

        explanation = explanation_to_dict(result)
        detail_payload = {
            "run_id": run_id,
            "features": explanation,
            "algorithm": algorithm_identity(algorithm),
        }
        resolution = make_resolution(
            entity_id=entity_id_a,
            canonical_id=entity_id_b,
            judgement="unsure",
            decided_by="auto",
            decided_at=decided_at,
            score=result.score,
            decided_by_detail=json.dumps(detail_payload, sort_keys=True),
        )
        resolution_id = store.append_resolution(resolution)
        suggested.append(
            CrossrefCandidate(
                entity_id_a=entity_id_a,
                entity_id_b=entity_id_b,
                score=result.score,
                explanation=explanation,
                resolution_id=resolution_id,
            )
        )

    return suggested
