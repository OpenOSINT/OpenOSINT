# tests/test_graph_provenance.py
"""Tests for openosint.graph.provenance — the extractor_confidence/run_id/method sidecar."""

from __future__ import annotations

import pytest

pytest.importorskip("followthemoney", reason="requires the 'graph' extra")

from datetime import datetime, timedelta, timezone  # noqa: E402

from openosint.graph.provenance import make_provenance  # noqa: E402


def _valid_kwargs(**overrides):
    kwargs = dict(
        statement_id="abc123",
        run_id="run-1",
        collection_method="map_whois:email",
        extractor_confidence=0.9,
        collected_at=datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc),
    )
    kwargs.update(overrides)
    return kwargs


class TestMakeProvenance:
    def test_constructs_with_valid_fields(self):
        record = make_provenance(**_valid_kwargs())
        assert record.statement_id == "abc123"
        assert record.extractor_confidence == 0.9
        assert record.breach_name is None

    def test_confidence_above_one_raises(self):
        with pytest.raises(ValueError):
            make_provenance(**_valid_kwargs(extractor_confidence=1.5))

    def test_confidence_below_zero_raises(self):
        with pytest.raises(ValueError):
            make_provenance(**_valid_kwargs(extractor_confidence=-0.1))

    def test_naive_datetime_raises(self):
        with pytest.raises(ValueError):
            make_provenance(**_valid_kwargs(collected_at=datetime(2026, 8, 25, 12, 0, 0)))

    def test_non_utc_timezone_raises(self):
        offset_tz = timezone(timedelta(hours=5))
        with pytest.raises(ValueError):
            make_provenance(
                **_valid_kwargs(collected_at=datetime(2026, 8, 25, 12, 0, 0, tzinfo=offset_tz))
            )

    def test_missing_statement_id_raises(self):
        with pytest.raises(ValueError):
            make_provenance(**_valid_kwargs(statement_id=""))

    def test_two_records_for_same_statement_id_are_independent(self):
        """Same statement observed twice (different runs) -> two records, not a merge."""
        first = make_provenance(**_valid_kwargs(run_id="run-1"))
        second = make_provenance(**_valid_kwargs(run_id="run-2", extractor_confidence=0.6))
        assert first.statement_id == second.statement_id
        assert first.run_id != second.run_id
        assert first.extractor_confidence != second.extractor_confidence

    def test_breach_name_is_carried_when_supplied(self):
        record = make_provenance(**_valid_kwargs(breach_name="Adobe"))
        assert record.breach_name == "Adobe"
