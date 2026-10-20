"""
Sponsors data loader and validator.

Single source of truth: openosint/sponsors.json (packaged with the wheel).
Tiers: featured | integration | supporter
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

_SPONSORS_FILE = Path(__file__).parent / "sponsors.json"

VALID_TIERS = {"featured", "integration", "supporter"}
REQUIRED_FIELDS = {"name", "tagline", "url", "logo", "tier"}


class Sponsor(TypedDict, total=False):
    name: str
    tagline: str
    url: str
    logo: str
    tier: str
    tool: str
    category: str
    contact: str


class SponsorsValidationError(ValueError):
    pass


class SponsorsFileMissing(SponsorsValidationError):
    """sponsors.json is not on disk (a broken install; it ships inside the package)."""


def _validate(entry: dict, index: int) -> None:
    missing = REQUIRED_FIELDS - entry.keys()
    if missing:
        raise SponsorsValidationError(
            f"sponsors.json entry {index}: missing required fields: {sorted(missing)}"
        )
    tier = entry["tier"]
    if tier not in VALID_TIERS:
        raise SponsorsValidationError(
            f"sponsors.json entry {index} ({entry['name']!r}): "
            f"unknown tier {tier!r}. Valid tiers: {sorted(VALID_TIERS)}"
        )
    for field in REQUIRED_FIELDS:
        if not isinstance(entry[field], str) or not entry[field].strip():
            raise SponsorsValidationError(
                f"sponsors.json entry {index} ({entry.get('name', '?')!r}): "
                f"field {field!r} must be a non-empty string"
            )


def load_sponsors(path: Path | None = None) -> list[Sponsor]:
    """Load and validate sponsors from sponsors.json."""
    sponsors_path = path or _SPONSORS_FILE
    try:
        raw = json.loads(sponsors_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SponsorsFileMissing(f"sponsors.json not found at {sponsors_path}")
    except json.JSONDecodeError as exc:
        raise SponsorsValidationError(f"sponsors.json is not valid JSON: {exc}")

    if not isinstance(raw, list):
        raise SponsorsValidationError("sponsors.json must be a JSON array")

    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise SponsorsValidationError(f"sponsors.json entry {i}: must be an object")
        _validate(entry, i)

    return raw  # type: ignore[return-value]


def get_by_tier(tier: str, path: Path | None = None) -> list[Sponsor]:
    return [s for s in load_sponsors(path) if s["tier"] == tier]


def get_featured(path: Path | None = None) -> list[Sponsor]:
    return get_by_tier("featured", path)
