"""Lookalike domain candidates for a registrable domain. Pure and deterministic: no network."""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CANDIDATES = 300
# Most likely first when the list exceeds MAX_CANDIDATES: the variants most used in invoice/payment
# fraud (same name on another TLD, look-alike characters, small slips) come before the long tail.
TECHNIQUE_PRIORITY = (
    "tld_swap", "homoglyph", "homoglyph_idn", "omission", "swap",
    "repetition", "combo", "hyphenation", "keyboard", "insertion",
)
TLD_SWAPS = ("com", "net", "org", "it", "eu", "co", "io", "tech", "info", "biz")
KEYWORDS = ("login", "secure", "support", "billing", "invoice", "pay", "mail")
_COMBO_TLDS = ("com",)  # besides the input's own suffix
_QWERTY = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
_ASCII_HOMOGLYPHS = (("o", "0"), ("l", "1"), ("l", "i"), ("i", "1"), ("i", "l"), ("rn", "m"), ("m", "rn"), ("vv", "w"), ("w", "vv"))
_IDN_HOMOGLYPHS = {"a": "а", "c": "с", "e": "е", "i": "і", "l": "ӏ", "o": "о", "p": "р"}  # Cyrillic
_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


@dataclass(frozen=True)
class Candidate:
    domain: str  # ASCII only: IDN variants are always the punycode (xn--) form
    technique: str


def _neighbours() -> dict[str, tuple[str, ...]]:
    near: dict[str, set[str]] = {}
    for r, row in enumerate(_QWERTY):
        for i, key in enumerate(row):
            near[key] = set(row[max(0, i - 1): i + 2]) - {key}
            for other in (r - 1, r + 1):
                if 0 <= other < len(_QWERTY):
                    near[key] |= set(_QWERTY[other][max(0, i - 1): i + 2])
    return {k: tuple(sorted(v)) for k, v in near.items()}


_NEAR = _neighbours()  # digits and hyphens have no neighbours: they are never mutated this way


def _replace_each(label: str, old: str, new: str) -> set[str]:
    return {label[:m.start()] + new + label[m.end():] for m in re.finditer(re.escape(old), label)}


def _labels(label: str) -> dict[str, set[str]]:
    """Technique -> variant labels (without TLD). Unicode labels are punycoded later."""
    homoglyph = set().union(*(_replace_each(label, a, b) for a, b in _ASCII_HOMOGLYPHS))
    idn = {label[:i] + _IDN_HOMOGLYPHS[c] + label[i + 1:] for i, c in enumerate(label) if c in _IDN_HOMOGLYPHS}
    return {
        "homoglyph": homoglyph,
        "homoglyph_idn": idn,
        "omission": {label[:i] + label[i + 1:] for i in range(len(label))},
        "swap": {label[:i] + label[i + 1] + label[i] + label[i + 2:] for i in range(len(label) - 1) if label[i] != label[i + 1]},
        "repetition": {label[:i] + c + label[i:] for i, c in enumerate(label)},
        "hyphenation": {label[:i] + "-" + label[i:] for i in range(1, len(label))},
        "keyboard": {label[:i] + n + label[i + 1:] for i, c in enumerate(label) for n in _NEAR.get(c, ())},
        "insertion": {label[:i + j] + n + label[i + j:] for i, c in enumerate(label) for n in _NEAR.get(c, ()) for j in (0, 1)},
    }


def _ascii_label(label: str) -> str | None:
    """Punycode if needed; None if the result is not a valid DNS label."""
    try:
        ascii_label = label.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    return ascii_label if _LABEL_RE.match(ascii_label) else None


def generate(registrable: str, limit: int = MAX_CANDIDATES) -> tuple[tuple[Candidate, ...], int]:
    """(candidates kept in priority order, how many valid candidates were dropped over `limit`)."""
    label, _, suffix = registrable.partition(".")
    variants = _labels(label)
    variants["tld_swap"] = set()
    variants["combo"] = {f"{label}-{k}" for k in KEYWORDS} | {f"{k}-{label}" for k in KEYWORDS}
    per_label = {t: {(v, suffix) for v in vs} for t, vs in variants.items()}
    per_label["tld_swap"] = {(label, t) for t in TLD_SWAPS}
    per_label["combo"] = {(v, s) for v in variants["combo"] for s in dict.fromkeys((suffix, *_COMBO_TLDS))}

    seen = {registrable}
    ordered: list[Candidate] = []
    for technique in TECHNIQUE_PRIORITY:
        for variant, tld in sorted(per_label[technique]):
            ascii_label = _ascii_label(variant)
            domain = f"{ascii_label}.{tld}" if ascii_label else ""
            if ascii_label and domain not in seen:
                seen.add(domain)
                ordered.append(Candidate(domain, technique))
    ordered.sort(key=lambda c: (TECHNIQUE_PRIORITY.index(c.technique), c.domain))
    return tuple(ordered[:limit]), max(0, len(ordered) - limit)

