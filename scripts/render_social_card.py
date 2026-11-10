#!/usr/bin/env python
"""Render docs/assets/social-card.png (1280x640): the site's Open Graph / GitHub social preview.

    python scripts/render_social_card.py

Needs rsvg-convert (librsvg). The card is the logo mark plus the project hook on the site's ink background.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "assets" / "social-card.png"
SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640" viewBox="0 0 1280 640" font-family="Helvetica, Arial, sans-serif">
  <rect width="1280" height="640" fill="#16181b"/>
  <g transform="translate(96 88) scale(2.4)" fill="none" stroke="#ffffff">
    <rect x="8" y="8" width="44" height="44" stroke-width="5"/>
    <line x1="30" y1="14" x2="30" y2="46" stroke-width="2"/>
    <line x1="14" y1="30" x2="46" y2="30" stroke-width="2"/>
    <line x1="50" y1="50" x2="64" y2="64" stroke-width="6" stroke-linecap="square"/>
  </g>
  <text x="320" y="196" fill="#ffffff" font-size="72" font-weight="700" letter-spacing="2">OpenOSINT</text>
  <text x="96" y="336" fill="#ffffff" font-size="50" font-weight="700">The OSINT toolkit for AI agents</text>
  <text x="96" y="404" fill="#c9cdd1" font-size="34">Agent Skill, MCP server and CLI.</text>
  <text x="96" y="452" fill="#c9cdd1" font-size="34">Passive by default. No API keys needed to start.</text>
  <text x="96" y="500" fill="#c9cdd1" font-size="34">Every finding cites the tool call behind it.</text>
  <text x="96" y="580" fill="#8d949b" font-size="28">openosint.tech  ·  github.com/OpenOSINT/OpenOSINT</text>
</svg>
"""


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        svg = Path(tmp) / "card.svg"
        svg.write_text(SVG, encoding="utf-8")
        subprocess.run(["rsvg-convert", "-w", "1280", "-h", "640", "-o", str(OUT), str(svg)], check=True)
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
