"""Guardrails against README/site docs drifting from the real tool catalog and version.

The tool count and version are derived from code (mcp_server.py, agent.py,
pyproject.toml), never hand-typed here — that's the whole point.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

# investigate_multi is an MCP-only batch-orchestration wrapper around
# multi_target.py, not a catalog data-source tool — agent.py doesn't expose
# it either, and it isn't listed in the README/tools-page catalog.
#
# graph_export / graph_neighbors / graph_review_candidates are the additive,
# `graph`-extra-gated openosint.graph subsystem's MCP tools (Phase 4) —
# scoped by design as MCP-only (see openosint/graph/__init__.py: "additive,
# sits alongside the existing Entity Correlation Graph... without modifying
# it"). They are not part of the "N investigation tools" README/docs count,
# which CLAUDE.md scopes explicitly to openosint/tools/ — and agent.py's
# natural-language tool loop deliberately does not expose them either.
_NON_CATALOG_TOOLS = {
    "investigate_multi",
    "graph_export",
    "graph_neighbors",
    "graph_review_candidates",
}

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


def test_mcp_registry_manifest_matches_tool_count_and_version():
    manifest = json.loads((ROOT / ".mcp" / "server.json").read_text(encoding="utf-8"))
    claim = _TOOL_COUNT_RE.search(manifest["description"])
    assert claim, "no tool count in .mcp/server.json description"
    assert int(claim.group(1)) == len(_mcp_server_tool_names())
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE).group(1)
    assert manifest["version"] == version
    assert {p["version"] for p in manifest["packages"]} == {version}


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
                mismatches.append(
                    f"{path.relative_to(ROOT)}: {match.group(0)!r} (expected {expected})"
                )
    assert not mismatches, "stale tool-count claim(s) found:\n" + "\n".join(mismatches)


# The public presence points at the hosted products only (app.openosint.tech).
# Legal pages are excluded: they still describe the live Apify Actors.
_RETIRED_PROMO_RE = re.compile(r"gumroad\.com|apify\.com|free-prompts|substack\.com", re.IGNORECASE)
_LEGAL_PAGES = {"privacy", "terms", "subprocessors"}


def test_no_retired_product_promotion():
    paths = [ROOT / "README.md", ROOT / "llms.txt"]
    for path in sorted((ROOT / "docs").rglob("*.html")):
        rel = path.relative_to(ROOT / "docs")
        if rel.parts[0] not in _LEGAL_PAGES:
            paths.append(path)
    hits = [
        f"{p.relative_to(ROOT)}: {m.group(0)!r}"
        for p in paths
        for m in _RETIRED_PROMO_RE.finditer(p.read_text(encoding="utf-8"))
    ]
    assert not hits, "retired product promotion found:\n" + "\n".join(hits)


# IP2Location and TestMu AI are paid, active sponsors: their placements on the
# home page and in the README must survive any future cleanup.
_SPONSOR_MARKERS = {
    "IP2Location": ["IP2Location", "https://www.ip2location.io/?utm_source=openosint", "ip2location-logo.png"],
    "TestMu AI": ["TestMu AI", "https://www.testmuai.com/?utm_source=openosint", "testmu-ai.svg"],
}


def test_home_and_readme_keep_sponsor_placements():
    pages = {
        "README.md": (ROOT / "README.md").read_text(encoding="utf-8"),
        "docs/index.html": (ROOT / "docs" / "index.html").read_text(encoding="utf-8").replace("&amp;", "&"),
    }
    missing = [
        f"{name}: {marker!r} missing from {rel}"
        for rel, text in pages.items()
        for name, markers in _SPONSOR_MARKERS.items()
        for marker in markers
        if marker not in text
    ]
    assert not missing, "sponsor placement(s) removed:\n" + "\n".join(missing)


# ---------------------------------------------------------------------------
# legal/*.md <-> docs/*/index.html mirror pairs must stay word-for-word
# identical in substance. Formatting differs by necessity (Markdown syntax vs
# HTML tags, and a link's visible text omitting the "https://" a raw URL in
# Markdown shows in full) — normalized to a word stream, ignoring those two
# known-and-accepted differences, the two sides must match exactly.
# ---------------------------------------------------------------------------

_MIRROR_PAIRS = [
    ("legal/PRIVACY_POLICY.md", "docs/privacy/index.html"),
    ("legal/TERMS_OF_SERVICE.md", "docs/terms/index.html"),
    ("legal/ACCEPTABLE_USE_POLICY.md", "docs/acceptable-use/index.html"),
]


def _tokenize(text: str) -> list[str]:
    text = text.replace("’", "'").replace("‘", "'")
    words = re.findall(r"[A-Za-z0-9']+", text.lower())
    # A Markdown raw URL (https://example.com/x) tokenizes with a leading
    # "https"/"http" that the same link's HTML anchor text never shows
    # (the visible text is "example.com/x", not the full URL) — not drift.
    return [w for w in words if w not in ("http", "https")]


def _normalize_markdown_body(text: str) -> list[str]:
    lines = [line for line in text.splitlines() if not line.startswith(">")]
    text = "\n".join(lines)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # [text](url) -> text
    text = re.sub(r"[#*`_>-]", " ", text)
    return _tokenize(text)


def _normalize_html_body(html_text: str) -> list[str]:
    import html as _html

    start = re.search(r'<h[12] id="intro"', html_text).start()
    end = html_text.index('<hr>\n<div id="footer">')
    body = _html.unescape(html_text[start:end])
    body = re.sub(r"<[^>]+>", " ", body)
    return _tokenize(body)


def test_legal_docs_match_their_html_mirror():
    mismatches = []
    for md_rel, html_rel in _MIRROR_PAIRS:
        md_words = _normalize_markdown_body((ROOT / md_rel).read_text(encoding="utf-8"))
        html_words = _normalize_html_body((ROOT / html_rel).read_text(encoding="utf-8"))
        if md_words != html_words:
            n = min(len(md_words), len(html_words))
            at = next((i for i in range(n) if md_words[i] != html_words[i]), n)
            mismatches.append(
                f"{md_rel} <-> {html_rel} diverge at word {at}: "
                f"{md_words[max(0, at - 6):at + 6]!r} vs {html_words[max(0, at - 6):at + 6]!r}"
            )
    assert not mismatches, "legal doc / HTML mirror drift:\n" + "\n".join(mismatches)
