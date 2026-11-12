"""Render docs/assets/logo-dark.svg (light ink, for dark themes) and logo-light.svg (dark ink) (magnifier glyph + OpenOSINT wordmark).

Text is converted to outlines so the SVGs need no webfont on GitHub.
Needs: pip install fonttools brotli.  Run: python scripts/make_logo.py
"""
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "docs/assets/fonts/InterTight-latin.woff2"
TEXT, SIZE, WEIGHT, TRACKING = "OpenOSINT", 30.0, 500, -0.01  # same as social.html
GLYPH, GAP, PAD, HEIGHT = 36.0, 14.0, 32.0, 96.0
# Transparent background; the file name says which GitHub theme it is for.
VARIANTS = {"dark": "#E6E6E6", "light": "#15171A"}


def wordmark_path(x0: float, baseline: float) -> tuple[str, float]:
    font = instancer.instantiateVariableFont(TTFont(FONT), {"wght": WEIGHT})
    scale = SIZE / font["head"].unitsPerEm
    glyphs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
    x, parts = x0, []
    for ch in TEXT:
        name = cmap[ord(ch)]
        pen = SVGPathPen(glyphs)
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x, baseline)))
        parts.append(pen.getCommands())
        x += hmtx[name][0] * scale + TRACKING * SIZE
    return " ".join(parts), x - x0


def main() -> None:
    gx, gy = PAD, (HEIGHT - GLYPH) / 2
    text_x = gx + GLYPH + GAP
    path, text_w = wordmark_path(text_x, HEIGHT / 2 + SIZE * 0.36)
    width = round(text_x + text_w + PAD)
    for name, ink in VARIANTS.items():
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {HEIGHT:g}" '
            f'width="{width}" height="{HEIGHT:g}" role="img" aria-label="OpenOSINT">\n'
            f'<g transform="translate({gx:g} {gy:g}) scale({GLYPH / 24:g})" fill="none" stroke="{ink}" '
            f'stroke-width="1.8" stroke-linecap="square"><circle cx="11" cy="11" r="7"/><path d="M16.5 16.5 21 21"/></g>\n'
            f'<path fill="{ink}" d="{path}"/>\n</svg>\n'
        )
        (ROOT / f"docs/assets/logo-{name}.svg").write_text(svg, encoding="utf-8")


if __name__ == "__main__":
    main()
