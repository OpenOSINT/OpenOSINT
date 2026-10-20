"""
Bright Data referral link constants for in-product placements
(CLI setup messages, web UI hints).
"""

from __future__ import annotations

_MAIN = "https://get.brightdata.com/984ni58s2oad"


def _link(medium: str, source: str = "github") -> str:
    return f"{_MAIN}?utm_source={source}&utm_medium={medium}"


BRIGHTDATA_LINK_CLI = _link("cli")
BRIGHTDATA_LINK_WEB = _link("web")
BRIGHTDATA_LINK_SITE_TOOLS = _link("tools", "site")
BRIGHTDATA_LINK_SITE_DOCS = _link("docs", "site")
