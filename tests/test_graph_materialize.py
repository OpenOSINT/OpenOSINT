# tests/test_graph_materialize.py
"""Tests for openosint.graph.materialize — export-time notes reconstruction.

"Test both paths" (correction 1): the sidecar path is covered by
tests/test_graph_mapping_breach.py (ProvenanceRecord.breach_name survives
per-breach). This file covers the export path — turning those sidecar
records back into a `notes`-shaped string, the only place that string exists.
"""

from __future__ import annotations

import pytest

pytest.importorskip("followthemoney", reason="requires the 'graph' extra")

from datetime import datetime, timezone  # noqa: E402

from openosint.graph.materialize import breach_notes_for_statement  # noqa: E402
from openosint.graph.provenance import make_provenance  # noqa: E402

_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)


def _record(**overrides):
    kwargs = dict(
        statement_id="stmt-1",
        run_id="run-1",
        collection_method="map_breach:email",
        extractor_confidence=0.9,
        collected_at=_NOW,
        breach_name=None,
    )
    kwargs.update(overrides)
    return make_provenance(**kwargs)


class TestBreachNotesForStatement:
    def test_no_breach_records_returns_none(self):
        records = [_record(breach_name=None)]
        assert breach_notes_for_statement(records) is None

    def test_empty_sequence_returns_none(self):
        assert breach_notes_for_statement([]) is None

    def test_single_breach_name(self):
        records = [_record(breach_name="Adobe")]
        assert breach_notes_for_statement(records) == "Found in breach(es): Adobe"

    def test_multiple_breach_names_preserve_first_seen_order(self):
        records = [_record(breach_name="LinkedIn"), _record(breach_name="Adobe")]
        assert breach_notes_for_statement(records) == "Found in breach(es): LinkedIn, Adobe"

    def test_duplicate_breach_name_across_runs_is_not_repeated(self):
        records = [
            _record(run_id="run-1", breach_name="Adobe"),
            _record(run_id="run-2", breach_name="Adobe"),
        ]
        assert breach_notes_for_statement(records) == "Found in breach(es): Adobe"

    def test_mixed_breach_and_non_breach_records_only_counts_breach_ones(self):
        records = [_record(breach_name=None), _record(breach_name="Adobe")]
        assert breach_notes_for_statement(records) == "Found in breach(es): Adobe"
