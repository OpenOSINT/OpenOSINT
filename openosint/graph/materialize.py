# openosint/graph/materialize.py
"""
Export-time materialization of sidecar-only facts into FtM property text.

WHY this is separate from mapping.py: ProvenanceRecord (the sidecar) is
OpenOSINT's own extension to FtM, not part of the FtM statement model. A
.ftm / NDJSON export (Phase 4's graph_export) has no sidecar to carry along —
so anything that only lives in the sidecar is lost the moment an entity
leaves this system, unless it is folded into a real FtM property first.

breach_name is the first fact of that kind (see provenance.py and
correction 1): it lives on ProvenanceRecord, not on any Statement value, so
map_breach() alone produces an entity with an `email` property but no
human-readable trace of which breaches drove it. This module is what
reconstructs that trace, and ONLY at export time — nothing in mapping.py or
Phase 2's store calls this; a `notes` value belongs in the store as an actual
statement only if a caller explicitly asks for one to be materialized.
"""

from __future__ import annotations

from collections.abc import Sequence

from openosint.graph.provenance import ProvenanceRecord


def breach_notes_for_statement(provenance_records: Sequence[ProvenanceRecord]) -> str | None:
    """Return a `notes`-property string summarizing breach findings, or None.

    Only records carrying a breach_name contribute. Order follows first
    appearance in *provenance_records*; duplicate breach names collapse to
    one mention (the same breach observed across multiple runs must not
    repeat itself in the exported text).
    """
    names: list[str] = []
    seen: set[str] = set()
    for record in provenance_records:
        if record.breach_name and record.breach_name not in seen:
            seen.add(record.breach_name)
            names.append(record.breach_name)
    if not names:
        return None
    return "Found in breach(es): " + ", ".join(names)
