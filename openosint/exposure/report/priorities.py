"""Top-priority selection for the report summary."""

from __future__ import annotations

from openosint.exposure.models import Finding
from openosint.exposure.scoring import SCORING_WEIGHTS

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
TOP_N = 3


def sort_key(f: Finding) -> tuple[int, float, str]:
    """Severity first, then category multiplier (higher = more important), then id for stability."""
    multiplier = SCORING_WEIGHTS["category_multiplier"].get(f.category, 1.0)
    return (_SEVERITY_RANK[f.severity], -multiplier, f.id)


def top_priorities(findings: tuple[Finding, ...], n: int = TOP_N) -> list[Finding]:
    """Up to n most important findings. Info findings never qualify."""
    return sorted((f for f in findings if f.severity != "info"), key=sort_key)[:n]
