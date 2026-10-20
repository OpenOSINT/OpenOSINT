# openosint/graph/datasets.py
"""
FtM dataset naming — one dataset per OpenOSINT source module.

WHY this matters more than it looks: FtM's Statement.id is
sha1(dataset.entity_id.prop.value) (see followthemoney.statement.Statement.
make_key). If two source modules asserted the same property+value into the
*same* dataset, their statements would collapse to one id and one of the two
observations would silently vanish — exactly the "provenance lost" failure
Phase 1 exists to prevent. Giving every source module its own dataset name
keeps their statement ids distinct even when the asserted value is identical,
so first_seen/last_seen do the job of tracking repeat observations *within*
one module, and cross-module agreement is visible as multiple statements
rather than one.
"""

from __future__ import annotations

# Tools whose real-world source identity differs from their OpenOSINT tool
# name (the API/service being queried, not the internal function name).
_DATASET_OVERRIDES: dict[str, str] = {
    "search_breach": "hibp",
}


def dataset_for_tool(tool_name: str) -> str:
    """Return the FtM dataset name for statements produced from *tool_name*.

    Default rule: strip the "search_" prefix (search_whois -> whois,
    search_github -> github). A small override table handles the few tools
    whose backing service has a different, more specific name than the
    internal function (search_breach -> hibp, since HIBP is the actual
    data source being queried).
    """
    slug = _DATASET_OVERRIDES.get(tool_name, tool_name.removeprefix("search_"))
    return f"openosint:{slug}"
