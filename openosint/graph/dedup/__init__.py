# openosint/graph/dedup/__init__.py
"""
Phase 3 — non-destructive dedup via nomenklatura's cross-reference scoring.

WHY this whole submodule is gated, not just its imports: nomenklatura>=4.14.0
requires Python >=3.11, but this project's `requires-python` floor is 3.10
(Phases 1-2 have no nomenklatura dependency and must keep working there — the
Python floor bump is a separate, announced release, not implied by this
module existing). Importing ANY name from this package first runs this
__init__.py, so the version check below protects every submodule
automatically, however a caller tries to reach it.

CRITICAL — never auto-merge (unchanged from the original brief): everything
in this package only ever writes resolutions rows with judgement='unsure'
and decided_by='auto'. Nothing here ever writes judgement='positive'. A
human reviewing a suggested pair is what turns 'unsure' into 'positive' —
that happens elsewhere (Phase 4's review tool, not built yet), never
automatically as a side effect of scoring.
"""

from __future__ import annotations

import sys

from openosint.graph.dedup_guard import check_python_version

check_python_version(sys.version_info[:2])

try:
    import nomenklatura  # noqa: F401
except ImportError as exc:
    raise ImportError(
        "openosint.graph.dedup requires the 'nomenklatura' package, which is not "
        "installed in this environment. Install it with: pip install 'openosint[graph-dedup]'"
    ) from exc

from openosint.graph.dedup.candidates import block_candidates, same_schema_pairs  # noqa: E402
from openosint.graph.dedup.crossref import CrossrefCandidate, run_crossref  # noqa: E402
from openosint.graph.entity_proxy import build_entity_proxy  # noqa: E402

__all__ = [
    "CrossrefCandidate",
    "block_candidates",
    "build_entity_proxy",
    "run_crossref",
    "same_schema_pairs",
]
