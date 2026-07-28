"""Guardrails against README/site docs drifting from the real tool catalog and version.

The tool count and version are derived from code (mcp_server.py, agent.py,
pyproject.toml), never hand-typed here — that's the whole point.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

# investigate_multi is an MCP-only batch-orchestration wrapper around
# multi_target.py, not a catalog data-source tool — agent.py doesn't expose
# it either, and it isn't listed in the README/tools-page catalog.
_NON_CATALOG_TOOLS = {"investigate_multi"}

_TOOL_COUNT_RE = re.compile(
    r"(\d+)\+?\s*(?:intelligence[- ]gathering |intelligence |investigation |modular |OpenOSINT )*tools?\b",
    re.IGNORECASE,
)


def _mcp_server_tool_names() -> set[str]:
    src = (ROOT / "openosint" / "mcp_server.py").read_text(encoding="utf-8")
    return set(re.findall(r'name="([a-z0-9_]+)"', src)) - _NON_CATALOG_TOOLS


def _agent_tool_names() -> set[str]:
    src = (ROOT / "openosint" / "agent.py").read_text(encoding="utf-8")
    return set(re.findall(r'"name":\s*"([a-z0-9_]+)"', src)) - _NON_CATALOG_TOOLS


def _iter_doc_files():
    yield ROOT / "README.md"
    docs = ROOT / "docs"
    for path in sorted(docs.rglob("*.html")):
        if "blog" in path.relative_to(docs).parts:
            continue
        yield path


def test_agent_and_mcp_server_expose_the_same_tool_catalog():
    agent_names = _agent_tool_names()
    mcp_names = _mcp_server_tool_names()
    assert agent_names == mcp_names, (
        f"agent.py and mcp_server.py tool catalogs drifted apart: "
        f"only in agent.py: {agent_names - mcp_names}, only in mcp_server.py: {mcp_names - agent_names}"
    )


def test_readme_tools_table_row_count_matches_registered_tools():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    table_match = re.search(
        r"\| Tool \| Powered by \| What it investigates \|\n\|[-| ]+\|\n((?:\|.+\|\n)+)",
        readme,
    )
    assert table_match, "README tools table (Tool | Powered by | What it investigates) not found"
    rows = [line for line in table_match.group(1).splitlines() if line.strip()]
    assert len(rows) == len(_mcp_server_tool_names())


def test_docs_tools_page_row_count_matches_registered_tools():
    html = (ROOT / "docs" / "tools" / "index.html").read_text(encoding="utf-8")
    table_match = re.search(r"<table>\s*<tr><th>Tool</th>.*?</table>", html, re.DOTALL)
    assert table_match, "docs/tools/index.html tool reference table not found"
    row_count = len(re.findall(r"<tr>", table_match.group(0))) - 1  # minus header row
    assert row_count == len(_mcp_server_tool_names())


def test_every_tool_count_claim_matches_registered_tools():
    # HTML tags stripped first — markup between a number and the word "tools"
    # (e.g. a stat tile with the count and label in separate <div>s) would
    # otherwise hide a stale claim from a plain-text regex.
    expected = len(_mcp_server_tool_names())
    mismatches = []
    for path in _iter_doc_files():
        raw = path.read_text(encoding="utf-8")
        text = re.sub(r"<[^>]+>", " ", raw) if path.suffix == ".html" else raw
        for match in _TOOL_COUNT_RE.finditer(text):
            if int(match.group(1)) != expected:
                mismatches.append(f"{path.relative_to(ROOT)}: {match.group(0)!r} (expected {expected})")
    assert not mismatches, "stale tool-count claim(s) found:\n" + "\n".join(mismatches)


def test_docs_index_footer_version_matches_pyproject():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version_match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert version_match, "version not found in pyproject.toml"
    version = version_match.group(1)

    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    footer_match = re.search(r"OpenOSINT (\d+\.\d+\.\d+)", html)
    assert footer_match, "docs/index.html footer version (OpenOSINT X.Y.Z) not found"
    assert footer_match.group(1) == version


# --------------------------------------------------------------------------
# Phase 3 — Gumroad link, price, and page-count consistency for the two
# revenue products (Prompt Pack, Complete Kit). No in-repo source of truth
# exists for these (unlike tool count / version), so drift can only be
# caught by cross-checking every stated occurrence against every other.
# --------------------------------------------------------------------------


def _iter_all_doc_files():
    yield ROOT / "README.md"
    docs = ROOT / "docs"
    for path in sorted(docs.rglob("*.html")):
        yield path


_GUMROAD_LINK_RE = re.compile(
    r"https://tommasodev\.gumroad\.com/l/(ai-osint-prompt-pack|ai-osint-complete-kit)((?:/[A-Za-z0-9_-]+)?)\?"
)


def test_gumroad_links_share_base_url_and_offer_code_per_product():
    seen: dict[str, set[str]] = {}
    for path in _iter_all_doc_files():
        raw = path.read_text(encoding="utf-8")
        for product, offer_code in _GUMROAD_LINK_RE.findall(raw):
            seen.setdefault(product, set()).add(offer_code)
    mismatches = {product: codes for product, codes in seen.items() if len(codes) > 1}
    assert not mismatches, f"Gumroad links use inconsistent offer codes per product: {mismatches}"


# Each pattern anchors the price tightly to the product name (compare-card
# markup, "Get the pack/kit" CTAs, and "Name ($NN)" mentions) so unrelated
# dollar amounts elsewhere on the page can't be misattributed.
_PRICE_PATTERNS = {
    "Prompt Pack": [
        re.compile(
            r'<h4>(?:AI OSINT )?Prompt Pack(?:\s*<span[^>]*>[^<]*</span>)?</h4>\s*'
            r'<div class="price">\$(\d+(?:\.\d{2})?)</div>',
            re.IGNORECASE,
        ),
        re.compile(r"Get the (?:Prompt )?[Pp]ack[^$\n<]{0,15}\$(\d+(?:\.\d{2})?)", re.IGNORECASE),
        re.compile(r"(?:AI OSINT )?Prompt Pack\**\s*\(\$(\d+(?:\.\d{2})?)\)", re.IGNORECASE),
    ],
    "Complete Kit": [
        re.compile(
            r'<h4>(?:AI OSINT )?Complete Kit(?:\s*<span[^>]*>[^<]*</span>)?</h4>\s*'
            r'<div class="price">\$(\d+(?:\.\d{2})?)</div>',
            re.IGNORECASE,
        ),
        re.compile(r"Get the (?:Complete )?[Kk]it[^$\n<]{0,15}\$(\d+(?:\.\d{2})?)", re.IGNORECASE),
        re.compile(r"(?:AI OSINT )?Complete Kit\**\s*\(\$(\d+(?:\.\d{2})?)\)", re.IGNORECASE),
    ],
}


def test_stated_prices_are_identical_per_product():
    found: dict[str, set[str]] = {}
    for path in _iter_all_doc_files():
        raw = path.read_text(encoding="utf-8")
        for product, patterns in _PRICE_PATTERNS.items():
            for pattern in patterns:
                found.setdefault(product, set()).update(pattern.findall(raw))
    mismatches = {product: prices for product, prices in found.items() if len(prices) > 1}
    assert not mismatches, f"Inconsistent stated prices per product: {mismatches}"


_BANNED_PAGE_COUNT_RE = re.compile(r"\b\d+-page\b|\b\d+\s+pages?\b|\bpdf pages\b", re.IGNORECASE)


def test_no_banned_page_count_phrasing():
    violations = []
    for path in _iter_all_doc_files():
        raw = path.read_text(encoding="utf-8")
        for match in _BANNED_PAGE_COUNT_RE.finditer(raw):
            violations.append(f"{path.relative_to(ROOT)}: {match.group(0)!r}")
    assert not violations, "banned page-count phrasing found:\n" + "\n".join(violations)
