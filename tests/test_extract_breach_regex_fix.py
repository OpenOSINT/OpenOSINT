# tests/test_extract_breach_regex_fix.py
r"""Regression test for the _extract_breach regex fix.

The original pattern r"^\[+\]\s+(\S+)\s+\(" means "one-or-more literal '['
then ']'", not literal "[+]" (the + needed escaping). It never matched real
search_breach.py output and had zero prior test coverage — discovered while
building openosint/graph/mapping.py's map_breach, which depends on this
extractor actually finding breach entities.
"""

from __future__ import annotations

from openosint.correlation import EntityType, make_entity
from openosint.extractors import _extract_breach

_SEED = make_entity(EntityType.EMAIL, "jane@example.com", 1.0)


class TestExtractBreachRegexFix:
    def test_matches_real_search_breach_output(self):
        raw = (
            "Found in 2 breach(es) for 'jane@example.com':\n\n"
            "[+] Adobe (2013-10-04) — leaked: Emails, Passwords\n"
            "[+] LinkedIn (2012-05-05) — leaked: Emails\n"
        )
        entities, relationships = _extract_breach(raw, _SEED)
        assert {e.value for e in entities} == {"Adobe", "LinkedIn"}
        assert len(relationships) == 2
        assert all(rel.kind == "found_in_breach" for rel in relationships)

    def test_no_breaches_found_message_yields_nothing(self):
        entities, relationships = _extract_breach(
            "No breaches found for 'jane@example.com'.", _SEED
        )
        assert entities == []
        assert relationships == []
