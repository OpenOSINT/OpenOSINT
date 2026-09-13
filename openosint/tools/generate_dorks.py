# openosint/tools/generate_dorks.py
"""
Google dork URL generator.

Produces a set of targeted Google search URLs for a given
target string (name, email, username, or domain).
No external dependencies or network calls required.
"""

from __future__ import annotations

import logging
import urllib.parse

logger = logging.getLogger(__name__)

_DORK_TEMPLATES: list[str] = [
    '"{target}"',
    '"{target}" site:linkedin.com',
    '("{target}") (site:x.com OR site:twitter.com)',
    '"{target}" site:facebook.com',
    '"{target}" site:instagram.com',
    '"{target}" site:github.com',
    '"{target}" filetype:pdf',
    '"{target}" inurl:profile',
    '"{target}" resume OR cv',
    '"{target}" leaked OR breach OR dump',
    'intitle:"{target}"',
    '"{target}" -site:linkedin.com -site:facebook.com',
]

_GOOGLE_BASE = "https://www.google.com/search?q="


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_dork_osint(target: str) -> str:
    """
    Generate Google dork URLs for *target*.

    This tool does not perform any HTTP requests — it returns
    a list of URLs the analyst can open manually or feed to
    a browser automation tool.

    Returns
    -------
    str
        Formatted list of dork URLs.
    """
    logger.info("Generating dork URLs for: %s", target)

    lines = [f"Google dork URLs for '{target}':\n"]
    for template in _DORK_TEMPLATES:
        query = template.format(target=target)
        encoded = urllib.parse.quote(query)
        lines.append(f"[+] {query}")
        lines.append(f"    {_GOOGLE_BASE}{encoded}\n")

    logger.info("Dork generation complete for: %s", target)
    return "\n".join(lines)
