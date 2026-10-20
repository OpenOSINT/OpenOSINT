# openosint/graph/dedup/candidates.py
"""
Candidate-pair generation for cross-reference scoring.

Pure: takes an already-fetched list of (entity_id, schema) pairs, returns
which pairs are worth scoring. No I/O, no nomenklatura import needed here —
this module only decides WHICH pairs to compare, scoring.py decides HOW.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from itertools import combinations

# The only schemas Phase 1's map_* functions ever assign as a primary entity
# (see mapping.py). Restricting to this fixed set is also what keeps this
# module from ever touching bridge/infra nodes — those never appear in
# `statements.schema` at all (Q1: IP/domain/hash/ASN/URL never become FtM
# entities), so there is nothing to explicitly filter out here; the
# invariant is enforced upstream, this is just documentation of why.
MATCHABLE_SCHEMAS = frozenset({"Person", "LegalEntity", "Organization", "UserAccount"})


def same_schema_pairs(entities: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    """Return every unordered pair of same-schema entities worth scoring.

    Working default: compares every pair within a schema, O(n^2) per schema
    group. Only entities whose schema is in MATCHABLE_SCHEMAS are considered
    — cross-schema comparison (a Person vs. an Organization) is never
    meaningful for same_as purposes and is skipped outright.

    Fine at the scale one OSINT investigation's graph reaches (tens to a few
    hundred entities per schema); a real deployment tracking thousands of
    entities per schema would want smarter blocking first — see
    block_candidates() below.
    """
    by_schema: dict[str, list[str]] = defaultdict(list)
    for entity_id, schema in entities:
        if schema in MATCHABLE_SCHEMAS:
            by_schema[schema].append(entity_id)

    pairs: list[tuple[str, str]] = []
    for ids in by_schema.values():
        pairs.extend(combinations(sorted(ids), 2))
    return pairs


def block_candidates(
    entities: Sequence[tuple[str, str]], *, max_pairs: int
) -> list[tuple[str, str]]:
    """Return a SMALLER, smarter candidate set than same_schema_pairs()'s full O(n^2) scan.

    WHY you should write this one by hand: same_schema_pairs() is correct but
    doesn't scale — a schema group of 2,000 Person entities is ~2 million
    pairs to score. A real blocking strategy groups entities by a coarse key
    likely to be shared only by genuine matches (a normalized name token, a
    shared identifier fragment, a shared property value) and only scores
    pairs within the same block — this is what nomenklatura's own
    nomenklatura.blocker.Index does at much larger scale, using DuckDB. That
    machinery assumes nomenklatura's own Store/Resolver/View abstractions,
    which this project doesn't use (GraphStore is a much simpler SQLite
    store) — reusing it directly isn't a good fit, but reading how it
    chooses blocking keys (nomenklatura/blocker/tokenizer.py) is worth doing
    before deciding your own key.

    Contract this must satisfy (see the failing tests in
    tests/test_graph_dedup_candidates.py::TestBlockCandidates):
      - Every pair returned must also be a pair same_schema_pairs() would
        return (never invent a cross-schema or unknown-schema pair).
      - len(result) <= max_pairs.
      - Pure function: same input -> same output, no I/O.

    To wire it in once implemented: crossref.py's run_crossref() takes a
    `candidate_fn` parameter defaulting to same_schema_pairs — pass
    block_candidates (partially applied with a max_pairs budget) instead.
    """
    raise NotImplementedError(
        "Phase 3 stub — see this function's docstring, then implement it and "
        "un-skip tests/test_graph_dedup_candidates.py::TestBlockCandidates."
    )
