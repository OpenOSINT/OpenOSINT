# openosint/graph/provenance.py
"""
Provenance sidecar for FtM statements.

WHY a sidecar and not fields on Statement itself: FtM's Statement already
carries dataset (source module), origin (free-text pointer, e.g. a breach
name or profile URL), and first_seen/last_seen (collection time) — reusing
those avoids inventing a parallel provenance model. What FtM's Statement
does NOT carry is a confidence score, which extractor produced the value, or
which OpenOSINT run observed it. Those live here.

WHY one-to-many keyed by statement_id, not one-to-one: Statement.id is
content-derived (dataset+entity_id+prop+value). Re-running the same tool
against the same target on a later day reproduces the *same* statement id
with a *different* run_id and possibly a different confidence. Each
observation gets its own ProvenanceRecord; nothing here overwrites a prior
one. The append-only store in Phase 2 is what actually enforces the
one-to-many storage — this dataclass just refuses to construct a record that
would be nonsensical to store (bad confidence, naive datetime).

TWO DIFFERENT CONFIDENCE SCALES — DO NOT AVERAGE THEM (correction 3):
`extractor_confidence` is an ORDINAL HEURISTIC — a hand-tuned score from
openosint/extractors.py, chosen to help pivot.py's BFS decide which
discoveries are worth chasing further. It is not a statistical estimate of
anything; "0.85" means "an extractors.py author judged this fairly
trustworthy", not "85% likely to be correct". Phase 3's nomenklatura
cross-reference index will produce genuinely CALIBRATED MATCH PROBABILITIES
for candidate same_as pairs — a different scale entirely, with a different
meaning and a different source (a scored classifier, not a hand-tuned
constant). That score belongs on the append-only `resolutions` table's
`score` column (Phase 2, requirement A), never here, and the two must never
be averaged, compared, or substituted for one another. If Phase 3 ever needs
to blend them, that blend is itself a documented decision, not a silent
arithmetic accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ProvenanceRecord:
    """One observation of one statement: how sure we were, and how we got it.

    breach_name is the first case of a source-specific structured fact that
    only the sidecar carries (see correction 1) — HIBP's breach name is not
    itself part of the `email` statement's value, it is *evidence* for that
    statement's truth, observed once per breach per run. If another source
    later needs the same treatment, give it its own optional field rather
    than overloading breach_name or reaching for a generic untyped blob.
    """

    statement_id: str
    run_id: str
    collection_method: str
    extractor_confidence: float
    collected_at: datetime
    breach_name: str | None = None


def make_provenance(
    *,
    statement_id: str,
    run_id: str,
    collection_method: str,
    extractor_confidence: float,
    collected_at: datetime,
    breach_name: str | None = None,
) -> ProvenanceRecord:
    """Construct a ProvenanceRecord, validating the fields Statement can't check.

    Raises
    ------
    ValueError
        If extractor_confidence is outside [0, 1], or collected_at is not a
        timezone-aware UTC datetime. Both are trust-boundary inputs supplied
        by the caller (Phase 2's orchestrator), not derived internally, so
        they are validated here rather than assumed correct.
    """
    if not statement_id:
        raise ValueError("statement_id is required")
    if not run_id:
        raise ValueError("run_id is required")
    if not collection_method:
        raise ValueError("collection_method is required")
    if not 0.0 <= extractor_confidence <= 1.0:
        raise ValueError(f"extractor_confidence must be in [0, 1], got {extractor_confidence!r}")
    if collected_at.tzinfo is None or collected_at.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError("collected_at must be a timezone-aware UTC datetime")
    return ProvenanceRecord(
        statement_id=statement_id,
        run_id=run_id,
        collection_method=collection_method,
        extractor_confidence=extractor_confidence,
        collected_at=collected_at,
        breach_name=breach_name,
    )
