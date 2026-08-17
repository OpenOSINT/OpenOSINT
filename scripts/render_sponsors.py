#!/usr/bin/env python3
"""
Render the sponsors block in README.md from sponsors.json.

Usage:
    python scripts/render_sponsors.py           # update README.md in-place
    python scripts/render_sponsors.py --check   # exit 1 if README is out of sync

Markers (created automatically if absent):
    <!-- SPONSORS:START -->
    <!-- SPONSORS:END -->

Pass --docs-html to also sync the sponsor cards on docs/sponsors.html from the
same sponsors.json (markers: <!-- SPONSORS-HTML:START/END -->). Opt-in and off
by default so this script's default behavior — and the existing test suite —
is unchanged.

Running this script is idempotent: re-running it produces the same output.
Wire it to CI or pre-commit to keep README in sync:

    pre-commit: python scripts/render_sponsors.py --check
    CI step:    python scripts/render_sponsors.py --docs-html docs/sponsors.html && git diff --exit-code README.md docs/sponsors.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_README = _REPO_ROOT / "README.md"
_SPONSORS_FILE = _REPO_ROOT / "sponsors.json"

START_MARKER = "<!-- SPONSORS:START -->"
END_MARKER = "<!-- SPONSORS:END -->"

HTML_START_MARKER = "<!-- SPONSORS-HTML:START -->"
HTML_END_MARKER = "<!-- SPONSORS-HTML:END -->"

VALID_TIERS = {"featured", "integration", "supporter"}
REQUIRED_FIELDS = {"name", "tagline", "url", "logo", "tier"}

# Full category list for the "open slots" line — keep in sync with the
# category table in SPONSORSHIP.md.
ALL_CATEGORIES = [
    "Breach / Compromised-Credential Data",
    "Email / Identity Lookup",
    "IP Geolocation & Threat Intelligence",
    "Residential Proxies",
]


# ---------------------------------------------------------------------------
# Validation (stdlib-only, no openosint import so the script is self-contained)
# ---------------------------------------------------------------------------


def _load_and_validate(path: Path) -> list[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"[render_sponsors] ERROR: {path} not found")
    except json.JSONDecodeError as exc:
        sys.exit(f"[render_sponsors] ERROR: {path} is not valid JSON: {exc}")

    if not isinstance(raw, list):
        sys.exit("[render_sponsors] ERROR: sponsors.json must be a JSON array")

    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            sys.exit(f"[render_sponsors] ERROR: entry {i} is not an object")
        missing = REQUIRED_FIELDS - entry.keys()
        if missing:
            sys.exit(f"[render_sponsors] ERROR: entry {i} missing fields: {sorted(missing)}")
        if entry["tier"] not in VALID_TIERS:
            sys.exit(
                f"[render_sponsors] ERROR: entry {i} ({entry['name']!r}) "
                f"has unknown tier {entry['tier']!r}"
            )
    return raw


# ---------------------------------------------------------------------------
# Block renderer
# ---------------------------------------------------------------------------


def _render_block(sponsors: list[dict]) -> str:
    lines: list[str] = [START_MARKER, ""]

    featured = [s for s in sponsors if s["tier"] == "featured"]
    integration = [s for s in sponsors if s["tier"] == "integration"]
    supporter = [s for s in sponsors if s["tier"] == "supporter"]

    if featured:
        lines.append("### Featured Integrations")
        lines.append("")
        for s in featured:
            logo = s.get("html_logo", s["logo"])
            logo_dark = s.get("html_logo_dark")
            if logo_dark:
                width = s.get("logo_width", 400)
                img_tag = (
                    "<picture>"
                    f'<source media="(prefers-color-scheme: dark)" srcset="{logo_dark}">'
                    f'<img src="{logo}" alt="{s["name"]} logo" width="{width}">'
                    "</picture>"
                )
            else:
                img_tag = f'<img src="{logo}" alt="{s["name"]} logo" height="40">'
            tool_note = f" — powers `{s['tool']}`" if s.get("tool") else ""
            doc_note = (
                f" · [Integration guide]({s['integration_doc']})"
                if s.get("integration_doc")
                else ""
            )
            lines.append(f'<a href="{s["url"]}" rel="noopener sponsored">{img_tag}</a>')
            lines.append("")
            lines.append(f"**[{s['name']}]({s['url']})**{tool_note}{doc_note}")
            lines.append("")
            lines.append(f"> {s['tagline']}")
            lines.append("")

    if integration:
        lines.append("### Integrations")
        lines.append("")
        for s in integration:
            lines.append(
                f"| [![{s['name']}]({s['logo']})]({s['url']}) "
                f"| **[{s['name']}]({s['url']})** | {s['tagline']} |"
            )
        lines.append("")

    if supporter:
        lines.append("### Supporters")
        lines.append("")
        for s in supporter:
            lines.append(f"[![{s['name']}]({s['logo']})]({s['url']})")
        lines.append("")

    taken_categories = {s.get("category") for s in sponsors}
    open_categories = [c for c in ALL_CATEGORIES if c not in taken_categories]
    if open_categories:
        lines.append(
            f"_Open: {' · '.join(open_categories)} — see [SPONSORSHIP.md](SPONSORSHIP.md)._"
        )
    else:
        lines.append(
            "_Want to sponsor OpenOSINT? See [SPONSORSHIP.md](SPONSORSHIP.md) for tiers and rates._"
        )
    lines.append("")
    lines.append(END_MARKER)
    return "\n".join(lines)


def _js_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _render_html_array(sponsors: list[dict]) -> str:
    """Render the sponsor-card JS array consumed by docs/sponsors.html."""
    featured = [s for s in sponsors if s["tier"] == "featured"]

    lines = [HTML_START_MARKER, "var SPONSORS = ["]
    for i, s in enumerate(featured):
        html_logo = s.get("html_logo", s["logo"])
        html_logo_dark = s.get("html_logo_dark", "")
        logo_alt = f"{s['name']} logo — sponsor for {s.get('category', s['name'])}"
        comma = "," if i < len(featured) - 1 else ""
        lines.append("  {")
        lines.append(f"    name:        {_js_string(s['name'])},")
        lines.append(f"    url:         {_js_string(s['url'])},")
        lines.append(f"    logo:        {_js_string(html_logo)},")
        lines.append(f"    logo_dark:   {_js_string(html_logo_dark)},")
        lines.append(f"    logo_alt:    {_js_string(logo_alt)},")
        lines.append(f"    category:    {_js_string(s.get('category', ''))},")
        lines.append(f"    description: {_js_string(s.get('tagline_full', s['tagline']))}")
        lines.append("  }" + comma)
    lines.append("];")
    lines.append(HTML_END_MARKER)
    return "\n".join(lines)


def _inject_docs_html(html_text: str, block: str) -> str:
    """Replace content between the HTML SPONSORS-HTML markers (inclusive)."""
    if HTML_START_MARKER not in html_text:
        sys.exit(
            f"[render_sponsors] ERROR: {HTML_START_MARKER} not found in docs HTML file. "
            "Add the marker pair around the `var SPONSORS = [...]` block first."
        )

    start_idx = html_text.index(HTML_START_MARKER)
    end_idx = html_text.index(HTML_END_MARKER, start_idx) + len(HTML_END_MARKER)
    return html_text[:start_idx] + block + html_text[end_idx:]


# ---------------------------------------------------------------------------
# README updater
# ---------------------------------------------------------------------------


def _inject(readme_text: str, block: str) -> str:
    """Replace content between START and END markers (inclusive)."""
    if START_MARKER not in readme_text:
        return readme_text.rstrip("\n") + "\n\n## Sponsors\n\n" + block + "\n"

    start_idx = readme_text.index(START_MARKER)
    end_idx = readme_text.index(END_MARKER, start_idx) + len(END_MARKER)
    return readme_text[:start_idx] + block + readme_text[end_idx:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit with code 1 if README.md is out of sync (do not write).",
    )
    parser.add_argument(
        "--readme",
        type=Path,
        default=_README,
        help="Path to README.md (default: repo root README.md).",
    )
    parser.add_argument(
        "--sponsors",
        type=Path,
        default=_SPONSORS_FILE,
        help="Path to sponsors.json (default: repo root sponsors.json).",
    )
    parser.add_argument(
        "--docs-html",
        type=Path,
        default=None,
        help=(
            "Path to docs/sponsors.html. When given, also regenerates its sponsor-card "
            "JS array from sponsors.json (opt-in; omit to touch README only)."
        ),
    )
    args = parser.parse_args()

    sponsors = _load_and_validate(args.sponsors)
    block = _render_block(sponsors)

    readme_text = args.readme.read_text(encoding="utf-8")
    updated = _inject(readme_text, block)

    targets = [(args.readme, readme_text, updated)]

    if args.docs_html is not None:
        html_text = args.docs_html.read_text(encoding="utf-8")
        html_block = _render_html_array(sponsors)
        html_updated = _inject_docs_html(html_text, html_block)
        targets.append((args.docs_html, html_text, html_updated))

    if args.check:
        out_of_sync = [path for path, before, after in targets if before != after]
        if out_of_sync:
            for path in out_of_sync:
                print(f"[render_sponsors] {path} sponsors block is out of sync.")
            print(
                "Run:  python scripts/render_sponsors.py"
                + (" --docs-html <path>" if args.docs_html else "")
            )
            sys.exit(1)
        for path, _before, _after in targets:
            print(f"[render_sponsors] {path} is up to date.")
        return

    for path, before, after in targets:
        if after != before:
            path.write_text(after, encoding="utf-8")
            print(f"[render_sponsors] Updated {path}")
        else:
            print(f"[render_sponsors] {path} already up to date.")


if __name__ == "__main__":
    main()
