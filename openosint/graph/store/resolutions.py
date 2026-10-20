# openosint/graph/store/resolutions.py
"""
Merge-decision records — requirement A: merge decisions never mutate statements.

Modeled on nomenklatura's Edge/Judgement vocabulary (nomenklatura.judgement.
Judgement: positive/negative/unsure/no_judgement, plus source/target/score/
user/created_at on its Edge) so Phase 3's real nomenklatura cross-reference
output maps onto this table with no impedance mismatch. The literal
nomenklatura package isn't imported yet — it requires Python >=3.11 and this
project's `requires-python` floor is 3.10 — so JUDGEMENTS below is this
module's own copy of that vocabulary, not an import.

WHY resolutions are append-only with no UPDATE path: a canonical_id column on
`statements` would be one UPDATE away from silently rewriting history — the
exact failure mode requirement A exists to prevent. Instead, "which entity is
canonical for X" is always a QUERY, never a stored, mutable fact.

CORRECTION (cluster semantics): the canonical id for X is NOT simply "the
latest row for entity_id=X" — that only handles a single pair, not a chain of
merges (A<->B, B<->C must make A and C resolve to the same canonical, even
with no direct A<->C row). GraphStore.canonical_for() computes the full
connected component of currently-active positive-judgement edges and returns
its max() id, the same way nomenklatura's Resolver.get_canonical() works.
Undoing one specific merge means appending a new row for the SAME PAIR of
entities with a non-positive judgement — a self-referencing row
(entity_id == canonical_id) does not correspond to any pair and has no effect
on clustering, which is why make_resolution() rejects entity_id == canonical_id
outright (mirroring nomenklatura's own Identifier.pair(), which raises on the
same case). revokes_resolution_id is audit metadata (which prior row this one
intends to revoke) — it does not itself drive the clustering computation;
"latest row per pair" does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

JUDGEMENTS = frozenset({"positive", "negative", "unsure", "no_judgement"})
DECIDED_BY_VALUES = frozenset({"human", "auto"})


@dataclass(frozen=True)
class Resolution:
    """One append-only merge-decision record: entity_id -> canonical_id.

    `id` is None for a Resolution being constructed to append — the store
    assigns the real row id on insert. Reading a Resolution back from the
    store populates it, which is what makes revokes_resolution_id chains
    (row N revokes row `id`) reconstructable.

    `score`, when decided_by='auto', is a THIRD confidence scale — do not mix
    it with the other two (same discipline provenance.py's module docstring
    applies to extractor_confidence, correction 3). It is whatever
    ScoringAlgorithm the caller passed to run_crossref() produced (see
    openosint/graph/dedup/scoring.py) — with the project default, LogicV2, it
    is a RULE-BASED COMPOSITE SCORE from fixed-weight feature comparators
    (name/identifier/address match), NOT a calibrated P(match) from a trained
    classifier. "0.82" means "LogicV2's weighted rules judged this pair
    fairly similar", not "82% likely to be the same entity". Which threshold
    counted as "worth suggesting" for a given row, and which algorithm
    produced it, are recorded in decided_by_detail (run_id, feature
    explanations, algorithm name+version — see
    dedup.scoring.algorithm_identity) precisely so a score written today
    stays interpretable after a nomenklatura upgrade or an algorithm swap.
    A human decision (decided_by='human') normally leaves score=None — a
    reviewer's accept/reject is a judgement, not a re-score.
    """

    entity_id: str
    canonical_id: str
    judgement: str
    decided_by: str
    decided_at: datetime
    score: float | None = None
    decided_by_detail: str | None = None
    revokes_resolution_id: int | None = None
    id: int | None = None


def make_resolution(
    *,
    entity_id: str,
    canonical_id: str,
    judgement: str,
    decided_by: str,
    decided_at: datetime,
    score: float | None = None,
    decided_by_detail: str | None = None,
    revokes_resolution_id: int | None = None,
) -> Resolution:
    """Construct a Resolution, validating the fields the store's CHECK constraints also enforce.

    Validating here too (not just in SQL) means a bad Resolution fails fast
    in Python, with a clear message, before it ever reaches a database call.

    Raises
    ------
    ValueError
        If entity_id/canonical_id are empty, refer to the same entity
        (self-referencing rows no longer mean anything under cluster
        semantics — see the module docstring), judgement/decided_by are
        outside their fixed vocabularies, score (when given) is outside
        [0, 1], or decided_at is not a timezone-aware UTC datetime.
    """
    if not entity_id:
        raise ValueError("entity_id is required")
    if not canonical_id:
        raise ValueError("canonical_id is required")
    if entity_id == canonical_id:
        raise ValueError(
            "entity_id and canonical_id must differ — a resolution links two distinct "
            "entities; to revoke a prior merge, append a new row for the SAME pair with "
            "a non-positive judgement, not a self-referencing row"
        )
    if judgement not in JUDGEMENTS:
        raise ValueError(f"judgement must be one of {sorted(JUDGEMENTS)}, got {judgement!r}")
    if decided_by not in DECIDED_BY_VALUES:
        raise ValueError(
            f"decided_by must be one of {sorted(DECIDED_BY_VALUES)}, got {decided_by!r}"
        )
    if score is not None and not 0.0 <= score <= 1.0:
        raise ValueError(f"score must be in [0, 1], got {score!r}")
    if decided_at.tzinfo is None or decided_at.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError("decided_at must be a timezone-aware UTC datetime")
    return Resolution(
        entity_id=entity_id,
        canonical_id=canonical_id,
        judgement=judgement,
        decided_by=decided_by,
        decided_at=decided_at,
        score=score,
        decided_by_detail=decided_by_detail,
        revokes_resolution_id=revokes_resolution_id,
    )
