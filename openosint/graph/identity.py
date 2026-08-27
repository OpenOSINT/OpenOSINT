# openosint/graph/identity.py
"""
Deterministic FtM entity ids for structured identifiers only.

WHY: statements need a stable entity_id so that repeat observations of the
same domain/username/email land on the same FtM entity instead of minting a
new anonymous one every run. FollowTheMoney ships exactly this primitive —
followthemoney.util.make_entity_id — a SHA1 hash of the given parts plus a
key_prefix, so it is reused here rather than hand-rolled.

WHY schema must be the key_prefix: without it, a Person and a UserAccount
keyed on the same (service, username) pair would collide onto one entity id,
silently merging two different schemas' worth of statements.

WHY this must NEVER be called with a free-text `name`: nomenklatura's Phase 3
cross-reference is what decides whether two same-named people are the same
person — that is a scored, human-reviewed judgment call. If entity ids were
derived from name strings here, two different "John Smith"s discovered by
different tools would collapse into one entity before any review happens,
which is exactly the silent auto-merge the whole project design forbids.
Only call this with values that are themselves strong identifiers: an email
address, a (service, username) pair, a domain name. Names are only ever
written as a `name` PROPERTY on an entity keyed some other way.
"""

from __future__ import annotations

from followthemoney.util import make_entity_id


def entity_id_for(schema: str, *key_parts: str) -> str:
    """Return a deterministic FtM entity id for *schema* keyed on *key_parts*.

    Parameters
    ----------
    schema:
        The FtM schema name this id is for (e.g. "UserAccount", "LegalEntity").
        Used as the hash key_prefix so the same key_parts never collide across
        different schemas.
    key_parts:
        One or more STRUCTURED identifier strings (already normalized by the
        caller). Never pass a free-text name — see module docstring.

    Raises
    ------
    ValueError
        If no non-empty key parts are given (make_entity_id would otherwise
        return None, an unstable and unusable id).
    """
    entity_id = make_entity_id(*key_parts, key_prefix=schema)
    if entity_id is None:
        raise ValueError("entity_id_for requires at least one non-empty key part")
    return entity_id
