# openosint/graph/names.py
"""
Minimal name extraction — deliberately narrow scope (decision C).

WHY this exists at all: without any Person names, nomenklatura's Phase 3
cross-reference index has nothing to match people on and the whole phase is
inert. This is NOT a general named-entity-recognition effort — it reads two
specific, already-labeled fields from two specific tools' formatted output.
Extending this to free-text extraction (bios, descriptions, WHOIS remarks)
is explicitly out of scope; ask before growing it.
"""

from __future__ import annotations

_PLACEHOLDER_VALUES = frozenset({"", "n/a", "none", "null", "unknown"})


def _is_placeholder(value: str) -> bool:
    return value.strip().lower() in _PLACEHOLDER_VALUES


def extract_github_name(raw: str) -> str | None:
    """Return the GitHub profile display name from search_github output.

    Reads the exact `[GitHub] Name: ...` line emitted by
    search_github.py::_format_profile. Returns None if the line is absent,
    empty, or the API's own "N/A" placeholder (search_github.py substitutes
    "N/A" when GitHub returns no `name` field).
    """
    prefix = "[GitHub] Name:"
    for line in raw.splitlines():
        if line.startswith(prefix):
            name = line[len(prefix) :].strip()
            return None if _is_placeholder(name) else name
    return None


def extract_whois_registrant_name(raw: str) -> str | None:
    """Return the WHOIS registrant name from search_whois output, or None if masked/absent.

    WHY you should write this one by hand: registrant "Name" is the messiest
    field in WHOIS data. It's sometimes a person, sometimes a company
    (indistinguishable from Org without more context), present only for some
    TLDs/registrars, and masked by privacy proxies even more aggressively
    than Org — registrars redact the contact name first. Writing this forces
    you to look at real WHOIS output across a few TLDs and decide how
    conservative to be about what counts as "a name".

    Contract this must satisfy (see the failing test in
    tests/test_graph_names.py::test_extract_whois_registrant_name_returns_real_name):
      - Read the `[+] Name: ...` line added to search_whois.py's
        _format_whois_results (this Phase 1 change already ships the line).
      - Run the value through denylist.is_privacy_masked() exactly the way
        extract_github_name skips its own placeholder — a masked registrant
        name must return None, never the denylist string itself.
      - Return None if the line is absent (thin registries, no name field).

    This is intentionally left unimplemented — see the WORKING STYLE note in
    the top-level task: one function per phase is yours to write.
    """
    raise NotImplementedError(
        "Phase 1 stub — see this function's docstring, then implement it and "
        "un-skip tests/test_graph_names.py::test_extract_whois_registrant_name_returns_real_name."
    )
