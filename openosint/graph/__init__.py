# openosint/graph/__init__.py
"""
FollowTheMoney entity/statement layer — additive, sits alongside the existing
Entity Correlation Graph (openosint/correlation.py, extractors.py, pivot.py)
without modifying it.

Phase 1 scope: pure functions that turn parsed OSINT findings into FtM
Statements with statement-level provenance. No I/O, no network, no DB here —
that begins in Phase 2's append-only store.
"""

from openosint.graph.bridge import BridgeLink
from openosint.graph.datasets import dataset_for_tool
from openosint.graph.denylist import is_privacy_masked
from openosint.graph.identity import entity_id_for
from openosint.graph.mapping import EmissionResult, map_breach, map_github, map_whois
from openosint.graph.materialize import breach_notes_for_statement
from openosint.graph.names import extract_github_name, extract_whois_registrant_name
from openosint.graph.provenance import ProvenanceRecord, make_provenance

__all__ = [
    "BridgeLink",
    "EmissionResult",
    "ProvenanceRecord",
    "breach_notes_for_statement",
    "dataset_for_tool",
    "entity_id_for",
    "extract_github_name",
    "extract_whois_registrant_name",
    "is_privacy_masked",
    "make_provenance",
    "map_breach",
    "map_github",
    "map_whois",
]
