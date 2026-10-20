#!/usr/bin/env python
"""Render docs/favicon.svg into docs/favicon.ico and the PNG icons (white mark on a solid background).

    python scripts/render_favicons.py

Needs Pillow and a Chrome/Chromium binary (set CHROME to its path if it is not found).
Writes docs/favicon.ico (16+32+48), docs/apple-touch-icon.png (180), docs/icon-192.png, docs/icon-512.png.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
BACKGROUND = "#16181b"  # --ink in docs/style.css
MARK_COLOR = "#ffffff"
# name -> (pixel size, padding as a share of the size)
PNG_ICONS = {"apple-touch-icon.png": (180, 0.20), "icon-192.png": (192, 0.20), "icon-512.png": (512, 0.20)}
ICO_SIZES = {48: 0.125, 32: 0.125, 16: 0.125}
CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
    "chromium-browser",
)


def find_chrome() -> str:
    for candidate in (os.environ.get("CHROME", ""), *CHROME_CANDIDATES):
        if candidate and (Path(candidate).is_file() or shutil.which(candidate)):
            return candidate
    sys.exit("render_favicons: Chrome/Chromium not found; set CHROME to its path")


def mark_markup() -> str:
    """The SVG from docs/favicon.svg with its theme style replaced by a fixed light mark."""
    svg = (DOCS / "favicon.svg").read_text(encoding="utf-8")
    svg = re.sub(r"<style>.*?</style>", f"<style>.mark {{ stroke: {MARK_COLOR}; }}</style>", svg, flags=re.S)
    return re.sub(r'\s(width|height)="[^"]*"', "", svg, count=2)


def render(chrome: str, workdir: Path, size: int, padding: float, out: Path) -> None:
    pad = round(size * padding)
    page = workdir / f"icon_{size}.html"
    page.write_text(
        f"<!doctype html><meta charset=utf-8><style>html,body{{margin:0;width:{size}px;height:{size}px;"
        f"background:{BACKGROUND}}}svg{{position:absolute;left:{pad}px;top:{pad}px;"
        f"width:{size - 2 * pad}px;height:{size - 2 * pad}px}}</style>{mark_markup()}",
        encoding="utf-8",
    )
    subprocess.run(
        [
            chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
            f"--window-size={size},{size}", f"--screenshot={out}", page.as_uri(),
        ],
        check=True,
        capture_output=True,
    )


def main() -> int:
    chrome = find_chrome()
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for name, (size, padding) in PNG_ICONS.items():
            render(chrome, workdir, size, padding, DOCS / name)
        frames = []
        for size, padding in ICO_SIZES.items():
            out = workdir / f"ico_{size}.png"
            render(chrome, workdir, size, padding, out)
            frames.append(Image.open(out).convert("RGBA"))
        frames[0].save(
            DOCS / "favicon.ico", format="ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=frames[1:]
        )
    print("wrote favicon.ico, apple-touch-icon.png, icon-192.png, icon-512.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
