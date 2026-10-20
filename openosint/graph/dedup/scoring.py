# openosint/graph/dedup/scoring.py
"""
Wraps nomenklatura's ScoringAlgorithm — the actual matching intelligence.

WHY LogicV2, not nomenklatura's DedupeAlgorithm (EntityResolveRegression):
DedupeAlgorithm is a trained regression model — it needs downloaded model
weights, an extra runtime dependency this project has no reason to take on.
LogicV2 is rule-based (name/identifier/address comparators with fixed
weights, see nomenklatura.matching.logic_v2.model) — deterministic,
inspectable, no model file, and its explanations are exactly the "features
that drove the score" this phase is required to expose.

KNOWN CAVEAT — discovered while building this: nomenklatura's LogicV2 name
matching memoizes per-entity name analysis with an lru_cache keyed on
EntityProxy.__hash__, which hashes ONLY the entity's .id
(nomenklatura/matching/logic_v2/names/analysis.py). nomenklatura's own code
comment says so explicitly: "if the properties of the underlying entity
change, this cache will not be invalidated." Since entity_id_for() (Phase 1)
deliberately gives the SAME real-world identity a PERMANENT id across every
run, this means: if a long-lived process (e.g. an MCP server) calls
run_crossref() more than once, and an entity gained NEW statements between
those calls (a later scan discovered another email, say), the SECOND
crossref pass may score that entity using a STALE name analysis from before
the new data arrived — id reuse plus changed content is exactly the
situation the cache doesn't handle. This is nomenklatura's own documented
tradeoff (optimized for one xref() batch scanning one query entity against
many candidates), not something this wrapper works around by reaching into
nomenklatura's internals. Prefer running crossref in a fresh process per
pass until/unless nomenklatura changes this; a long-lived process should not
assume repeated crossref calls see fresh data for previously-scored entities.
"""

from __future__ import annotations

import nomenklatura
from followthemoney.proxy import EntityProxy
from nomenklatura.matching import LogicV2
from nomenklatura.matching.types import MatchingResult, ScoringAlgorithm, ScoringConfig

DEFAULT_ALGORITHM: type[ScoringAlgorithm] = LogicV2

# NOT a calibrated match probability (see resolutions.py's `score` field
# docstring — this is the same discipline applied to extractor_confidence in
# provenance.py, and the two/three scales must never be mixed). LogicV2 is
# rule-based: this is a composite of fixed-weight feature comparators, not a
# classifier's P(match). 0.5 is the current default — chosen as the
# "more likely a match than not" reading of that composite score, which
# biases run_crossref toward flooding the human review queue with candidates
# (false positives an analyst discards) rather than silently skipping true
# matches that never get suggested at all (false negatives no one ever sees,
# since nothing here ever auto-merges). Lower this only if the review queue
# is unmanageably noisy; raise it only if real same_as pairs are being
# missed — both are judgment calls about analyst workload, not a property of
# the algorithm, so change it deliberately and record why.
DEFAULT_CROSSREF_THRESHOLD: float = 0.5


def score_pair(
    left: EntityProxy,
    right: EntityProxy,
    *,
    algorithm: type[ScoringAlgorithm] = DEFAULT_ALGORITHM,
) -> MatchingResult:
    """Score one candidate pair, returning the overall score and per-feature explanations."""
    return algorithm.compare(left, right, ScoringConfig.defaults())


def algorithm_identity(algorithm: type[ScoringAlgorithm]) -> dict[str, str]:
    """Return {"name": ..., "version": ...} identifying which algorithm produced a score.

    Meant to be embedded in Resolution.decided_by_detail (see crossref.py) —
    a LogicV2 score written today has fixed feature weights baked into
    *this* installed nomenklatura release; a future nomenklatura upgrade (or
    swapping DEFAULT_ALGORITHM entirely) can change what "0.82" meant. The
    algorithm class itself carries no version of its own (LogicV2.NAME is
    just "logic-v2"), so the installed package version stands in for it —
    the pair (name, version) is what makes an old score interpretable later.
    """
    return {"name": algorithm.NAME, "version": getattr(nomenklatura, "__version__", "unknown")}


def clear_stale_name_cache() -> None:
    """Best-effort mitigation for nomenklatura's undocumented lru_cache staleness bug.

    See this module's docstring above for the full bug: LogicV2's internal
    entity_names() memoizes per entity id (functools.lru_cache), and that
    cache key ignores the entity's actual property values. Call this once at
    the start of every run_crossref() pass (crossref.py does) so a long-lived
    process's Nth call re-analyzes every entity fresh instead of reusing a
    name analysis cached under the same id from an earlier call, before that
    entity's statements changed.

    Deliberately defensive: entity_names is not public nomenklatura API, so
    a future release could rename it, restructure the module, or drop the
    lru_cache entirely. Any of those makes this a silent no-op — this
    mitigates a staleness risk, it does not need to succeed for run_crossref
    to remain correct within a single pass, so a broken mitigation must never
    crash the pass that's calling it.
    """
    try:
        from nomenklatura.matching.logic_v2.names.analysis import entity_names

        entity_names.cache_clear()
    except (ImportError, AttributeError):
        pass


def explanation_to_dict(result: MatchingResult) -> dict[str, dict[str, object]]:
    """Flatten a MatchingResult's explanations into a JSON-serializable dict.

    This is what gets stored in Resolution.decided_by_detail (as JSON) so a
    human reviewing an 'unsure' candidate can see WHY it was suggested —
    which feature (name match, identifier match, ...) contributed, its own
    score, and which specific compared values drove it.
    """
    return {
        name: {
            "score": feature.score,
            "detail": feature.detail,
            "query": feature.query,
            "candidate": feature.candidate,
        }
        for name, feature in result.explanations.items()
    }
