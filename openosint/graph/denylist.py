# openosint/graph/denylist.py
"""
Privacy-proxy placeholder detection for WHOIS-style registrant/org fields.

WHY this exists: WHOIS registrars mask registrant identity with boilerplate
strings ("REDACTED FOR PRIVACY", "Domains By Proxy", ...). If those strings
become FtM entities, nomenklatura's Phase 3 cross-reference index will
same_as-link every domain that happens to share the same masking provider —
thousands of unrelated domains collapsed into one fake "entity". This filter
must run BEFORE any registrant value becomes a Statement, not after.

The phrase list lives in data/privacy_proxy_denylist.json, not in this file,
so it can be extended without a code change or review of matching logic.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files

_PUNCT_RE = re.compile(r"[^a-z0-9]+")


def _normalize(value: str) -> str:
    """Lowercase and collapse punctuation/whitespace runs to single spaces.

    WHY: registrars format the same placeholder inconsistently — "REDACTED
    FOR PRIVACY", "Redacted-For-Privacy", "redacted for privacy!!" must all
    match one denylist entry stored in one canonical form.
    """
    return _PUNCT_RE.sub(" ", value.lower()).strip()


@lru_cache(maxsize=1)
def _load_denylist() -> frozenset[str]:
    """Load and normalize the bundled denylist once per process.

    WHY cached: this is the only file read in the graph package. It happens
    once, at first use, not per call — the rest of this layer stays pure.
    """
    resource = files("openosint.graph.data").joinpath("privacy_proxy_denylist.json")
    phrases = json.loads(resource.read_text(encoding="utf-8"))
    return frozenset(_normalize(p) for p in phrases)


def is_privacy_masked(value: str) -> bool:
    """Return True if *value* is a WHOIS privacy-proxy placeholder, not a real name/org.

    Matching is substring-based on normalized text: "Whois Privacy Protection
    Service, Inc." must match the denylist entry "whois privacy protection
    service" even with the trailing corporate suffix and punctuation.
    """
    if not value or not value.strip():
        return False
    normalized = _normalize(value)
    return any(phrase in normalized for phrase in _load_denylist())
