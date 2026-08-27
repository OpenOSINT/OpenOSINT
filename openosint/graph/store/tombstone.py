# openosint/graph/store/tombstone.py
"""
The erasure tombstone — requirement B, the one documented exception to append-only.

CORRECTION (Phase 2 review): the original version of this module kept
subject_entity_id on the tombstone, reasoning that a SHA1 hash "cannot be
reversed" and was therefore safe to retain. That reasoning was wrong.
entity_id_for() is a DETERMINISTIC, UNSALTED function of a structured
identifier (see identity.py) — reversal isn't the threat, CONFIRMATION is: a
caller who suspects a specific email/domain/username was in the store can
recompute the same hash themselves and check whether it appears anywhere.
A surviving entity_id is a confirmation oracle, and under GDPR that still
counts as personal data about the erased subject. The tombstone therefore
keeps NOTHING derived from the subject's identifiers — only the erasure
event itself: when it happened, under what request id, and how many rows
were removed from each table. Nothing here can be used to test "was X in the
store".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ErasureTombstone:
    """Record that an erasure happened — never anything that identifies who or what."""

    request_id: str
    requested_at: datetime
    erased_statement_count: int
    erased_provenance_count: int
    erased_bridge_count: int
    erased_resolution_count: int


def make_tombstone(
    *,
    request_id: str,
    requested_at: datetime,
    erased_statement_count: int,
    erased_provenance_count: int,
    erased_bridge_count: int,
    erased_resolution_count: int,
) -> ErasureTombstone:
    """Construct an ErasureTombstone, validating the fields an audit trail depends on.

    Raises
    ------
    ValueError
        If request_id is empty, any erased_*_count is negative, or
        requested_at is not a timezone-aware UTC datetime.
    """
    if not request_id:
        raise ValueError("request_id is required")
    for name, count in (
        ("erased_statement_count", erased_statement_count),
        ("erased_provenance_count", erased_provenance_count),
        ("erased_bridge_count", erased_bridge_count),
        ("erased_resolution_count", erased_resolution_count),
    ):
        if count < 0:
            raise ValueError(f"{name} must be >= 0, got {count!r}")
    if requested_at.tzinfo is None or requested_at.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError("requested_at must be a timezone-aware UTC datetime")
    return ErasureTombstone(
        request_id=request_id,
        requested_at=requested_at,
        erased_statement_count=erased_statement_count,
        erased_provenance_count=erased_provenance_count,
        erased_bridge_count=erased_bridge_count,
        erased_resolution_count=erased_resolution_count,
    )
