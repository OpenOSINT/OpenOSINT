# openosint/graph/bridge.py
"""
Bridge links between the FtM statement layer and the existing EntityGraph.

WHY: Q1 keeps IP/domain/hash/ASN/URL out of the FtM layer entirely — they
stay exactly where they already are, in openosint.correlation.EntityGraph.
But an FtM entity is always derived FROM some EntityGraph node (a UserAccount
came from a username node, a WHOIS registrant LegalEntity came from a domain
node), and infra that belongs to an identity is folded into that identity's
FtM properties rather than kept as a separate node. Both directions need a
record so a later graph_neighbors(cross_layer=True) can still walk from an
FtM entity back into the untouched infra graph.

Bridge links are explicitly excluded from nomenklatura's Phase 3 index: they
describe navigation, not a matchable identity claim, and must never influence
same_as scoring.
"""

from __future__ import annotations

from dataclasses import dataclass

from openosint.correlation import EntityType


@dataclass(frozen=True)
class BridgeLink:
    """One edge between an FtM entity and an EntityGraph node.

    Parameters
    ----------
    ftm_entity_id:
        The FtM entity's id (from identity.entity_id_for).
    graph_entity_type, graph_entity_normalized:
        The EntityGraph node's dedup key — the same (type, normalized) pair
        EntityGraph itself uses internally — so this can be resolved back to
        the exact correlation.Entity without re-parsing anything.
    relation:
        What kind of link this is, e.g. "derived_from" (the FtM entity was
        built from this seed node) or "source_url" (this node's value was
        folded into the FtM entity as a url-typed property).
    """

    ftm_entity_id: str
    graph_entity_type: EntityType
    graph_entity_normalized: str
    relation: str
