#!/usr/bin/env python3
"""Record the graph web-UI demo (README hero GIF + docs WebM) with Playwright.

SYNTHETIC DATA ONLY — same rule as seed_demo.py, and it is load-bearing: the
rendered GIF is permanent and indexed once published. This script reuses the
fictional Aurora Dynamics scenario from seed_demo.py verbatim (same seeded
store, same frozen timestamps and run ids) and must never be pointed at a real
store or real data. It serves a throwaway SQLite store on localhost and never
touches the network.

What it records (the shot list, ~30s):
  1. Graph explorer: two Organization nodes, dashed same_as edge with score.
  2. Click node A  -> side panel: statements + provenance (dataset, run,
     extractor confidence).
  3. Click the dashed edge -> review card: score, feature explanation,
     side-by-side compare (green = match, amber = differs).
  4. Click Accept  -> graph updates in place: cluster box + solid same_as ✓.
  5. Close review  -> full-width final graph.

Determinism: the store is rebuilt from scratch on every run (frozen clock,
fixed run ids — see seed_demo.py), Math.random is replaced with a seeded PRNG
re-seeded before every Cytoscape init so the cose layout lands identically,
and there are no spinners or clocks on screen. The only run-to-run variance is
page-load time, which is measured and trimmed off the front of the video.

Usage:
    pip install playwright && playwright install chromium   # one-time
    python demo/web_demo.py

Outputs: demo/graph-web-demo.gif (README) and demo/graph-web-demo.webm (docs).
Requires ffmpeg on PATH for the conversion.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_GIF = REPO / "demo" / "graph-web-demo.gif"
OUT_WEBM = REPO / "demo" / "graph-web-demo.webm"

PORT = 8321  # fixed, demo-only; fails fast if taken
BASE = f"http://127.0.0.1:{PORT}"
VIEWPORT = {"width": 1280, "height": 720}
GIF_FPS = 10
GIF_WIDTH = 900  # README renders at 900px — no visible loss, much smaller file

# Cursor choreography (ms). CURSOR_TRAVEL_MS must match the CSS transition
# duration in CURSOR_SCRIPT below.
CURSOR_TRAVEL_MS = 600
PRE_CLICK_PAUSE_MS = 700

# Re-seed Math.random before every Cytoscape init so the cose layout is
# identical on every run AND on the post-accept in-place reload.
INIT_SCRIPT = """
(() => {
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  let realCytoscape = null;
  const wrapped = (...args) => {
    Math.random = mulberry32(1337);
    const cy = realCytoscape(...args);
    window.__cy = cy;   // demo hook: lets the recorder read node/edge pixels
    return cy;
  };
  Object.defineProperty(window, "cytoscape", {
    configurable: true,
    get: () => (realCytoscape ? wrapped : undefined),
    set: (fn) => { realCytoscape = fn; },
  });
})();
"""

# Demo-only legibility bump: the GIF is downscaled to GIF_WIDTH, which puts
# the review card's smallest text (match/differs tags, provenance sublines)
# at the edge of readability at README column width. Only injected while
# recording — the shipped UI is untouched.
DEMO_CSS = """
  #review .cmp .match-tag, #review .cmp .diff-tag { font-size: 12px; font-weight: 600; }
  #review .cmp .cell { font-size: 14px; }
  #review .cmp .cell .prov { font-size: 11px; }
  #review .feat .frow { font-size: 13px; }
  #review .feat .fval { font-size: 12px; }
  #review .score-hint { font-size: 12px; }
"""

# Visible cursor: Playwright doesn't record the mouse, so without this every
# click would be invisible. A dot that glides between targets + a click ripple.
CURSOR_SCRIPT = """
() => {
  const cur = document.createElement("div");
  Object.assign(cur.style, {
    position: "fixed", left: "640px", top: "620px", width: "16px", height: "16px",
    borderRadius: "50%", background: "#ffffffd9", border: "2px solid #0d1117",
    boxShadow: "0 0 8px #000c", zIndex: 2147483647, pointerEvents: "none",
    transform: "translate(-50%,-50%)",
    transition: "left .6s cubic-bezier(.22,.61,.36,1), top .6s cubic-bezier(.22,.61,.36,1)",
  });
  document.body.appendChild(cur);
  window.__cursor = {
    moveTo(x, y) { cur.style.left = x + "px"; cur.style.top = y + "px"; },
    ripple() {
      const r = document.createElement("div");
      Object.assign(r.style, {
        position: "fixed", left: cur.style.left, top: cur.style.top,
        width: "14px", height: "14px", borderRadius: "50%",
        border: "2px solid #58a6ff", zIndex: 2147483646, pointerEvents: "none",
        transform: "translate(-50%,-50%)", opacity: "1",
        transition: "width .4s ease-out, height .4s ease-out, opacity .4s ease-out",
      });
      document.body.appendChild(r);
      requestAnimationFrame(() => {
        r.style.width = "48px"; r.style.height = "48px"; r.style.opacity = "0";
      });
      setTimeout(() => r.remove(), 450);
    },
  };
}
"""


def die(msg: str) -> None:
    sys.exit(f"web_demo: {msg}")


def seed_store(demo_dir: Path) -> str:
    """Build the throwaway store + crossref candidate. Returns root entity id."""
    os.environ["OPENOSINT_DEMO_DIR"] = str(demo_dir)
    sys.path.insert(0, str(REPO / "demo"))
    import seed_demo  # reads OPENOSINT_DEMO_DIR at import time

    seed_demo.cmd_seed()
    # Same crossref pass the terminal demo runs; prints its narration, harmless.
    seed_demo.cmd_crossref()
    return seed_demo.ORG_A_ID


def start_server(db_path: Path) -> subprocess.Popen:
    env = {**os.environ, "OPENOSINT_GRAPH_DB": str(db_path)}
    proc = subprocess.Popen(
        [sys.executable, "-c",
         f"from openosint.web_server import run_server; run_server(port={PORT})"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        if proc.poll() is not None:
            die(f"server exited early (port {PORT} taken?)")
        try:
            with urllib.request.urlopen(f"{BASE}/graph", timeout=1) as r:
                if r.status == 200:
                    return proc
        except OSError:
            time.sleep(0.2)
    proc.terminate()
    die("server did not become ready in 15s")


class Cursor:
    """Drives the injected overlay in lockstep with real Playwright clicks."""

    def __init__(self, page):
        self.page = page
        page.evaluate(CURSOR_SCRIPT)

    def click_at(self, x: float, y: float) -> None:
        self.page.evaluate("([x,y]) => window.__cursor.moveTo(x,y)", [x, y])
        self.page.wait_for_timeout(CURSOR_TRAVEL_MS + PRE_CLICK_PAUSE_MS)
        self.page.evaluate("() => window.__cursor.ripple()")
        self.page.mouse.click(x, y)

    def click_element(self, selector: str) -> None:
        box = self.page.locator(selector).bounding_box()
        if not box:
            die(f"element not visible: {selector}")
        self.click_at(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def node_pixel(page, entity_id: str) -> tuple[float, float]:
    return tuple(page.evaluate(
        """(id) => {
          const cy = window.__cy;
          const p = cy.getElementById(id).renderedPosition();
          const r = cy.container().getBoundingClientRect();
          return [r.left + p.x, r.top + p.y];
        }""", entity_id))


def edge_pixel(page) -> tuple[float, float]:
    return tuple(page.evaluate(
        """() => {
          const cy = window.__cy;
          const p = cy.edges("[kind='same_as']").first().renderedMidpoint();
          const r = cy.container().getBoundingClientRect();
          return [r.left + p.x, r.top + p.y];
        }"""))


def record(root_id: str, video_dir: Path) -> tuple[Path, float]:
    """Drive the browser through the shot list.

    Returns (webm path, tail seconds): the tail is the wall time from
    scene-ready to the end of recording. Page-load time varies run to run, so
    the front trim is computed later as video_duration - tail — exact no
    matter how slow the cold start was.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport=VIEWPORT, record_video_dir=str(video_dir),
            record_video_size=VIEWPORT,
        )
        page = context.new_page()
        page.add_init_script(INIT_SCRIPT)

        # --- Shot 1: the graph — two orgs, dashed same_as edge with score ---
        page.goto(f"{BASE}/graph?entity_id={root_id}", wait_until="networkidle")
        page.wait_for_function("() => !!window.__cy")
        page.evaluate("() => window.__cy.fit(90)")
        page.add_style_tag(content=DEMO_CSS)
        cursor = Cursor(page)
        t_scene = time.time()
        page.wait_for_timeout(3000)

        # --- Shot 2: node A -> side panel with provenance ---
        cursor.click_at(*node_pixel(page, root_id))
        page.wait_for_selector("#side.open .stmt")
        page.wait_for_timeout(3500)

        # --- Shot 3: dashed edge -> review card ---
        cursor.click_at(*edge_pixel(page))
        page.wait_for_selector("#rv-foot.show")
        # The review panel halves the canvas; recenter what remains visible.
        page.evaluate("() => { window.__cy.resize(); window.__cy.fit(60); }")
        page.wait_for_timeout(6000)

        # --- Shot 4: Accept -> graph re-renders: cluster + solid edge ---
        cursor.click_element("#rv-accept")
        page.wait_for_selector("#rv-undo", state="visible")
        page.wait_for_function(
            "() => window.__cy.edges(\"[judgement='positive']\").length > 0")
        page.wait_for_timeout(2500)

        # --- Shot 5: close review -> full-width merged graph, hold ---
        cursor.click_element("#rv-close")
        page.evaluate("() => { window.__cy.resize(); window.__cy.fit(90); }")
        page.wait_for_timeout(3000)

        tail = time.time() - t_scene
        video = page.video
        context.close()  # flushes the recording
        browser.close()
        return Path(video.path()), tail


def video_duration(src: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(src)], check=True, capture_output=True, text=True)
    return float(out.stdout.strip())


def convert(src: Path, tail: float) -> None:
    """Two-pass palette GIF for the README + slim VP9 WebM for the docs site.

    mpdecimate is what keeps the GIF small: Playwright's VP8 recording adds
    invisible encoder noise, so without it every "static" frame still pays
    full price. Dropping near-duplicate frames turns each hold into one frame
    with a long GIF delay. tpad restores the final hold that trailing drops
    would otherwise cut, and dither=none is clean on this flat dark UI.
    """
    trim = max(0.0, video_duration(src) - tail)
    palette = src.parent / "palette.png"
    filters = (f"fps={GIF_FPS},scale={GIF_WIDTH}:-1:flags=lanczos,"
               "mpdecimate=hi=1024:lo=256:frac=0.05,"
               "tpad=stop_duration=2.5:stop_mode=clone")

    def run(*args: str) -> None:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)

    run("-ss", f"{trim:.2f}", "-i", str(src),
        "-vf", f"{filters},palettegen=stats_mode=diff", str(palette))
    run("-ss", f"{trim:.2f}", "-i", str(src), "-i", str(palette),
        "-lavfi", f"{filters} [x]; [x][1:v] paletteuse=dither=none",
        str(OUT_GIF))
    run("-ss", f"{trim:.2f}", "-i", str(src),
        "-c:v", "libvpx-vp9", "-crf", "40", "-b:v", "0", "-an", str(OUT_WEBM))


def main() -> None:
    if not shutil.which("ffmpeg"):
        die("ffmpeg not found on PATH")
    with tempfile.TemporaryDirectory(prefix="osint-web-demo-") as tmp:
        tmp_path = Path(tmp)
        store_dir = tmp_path / "store"
        root_id = seed_store(store_dir)
        server = start_server(store_dir / "graph.db")
        try:
            video, tail = record(root_id, tmp_path / "video")
            convert(video, tail)
        finally:
            server.terminate()
            server.wait(timeout=10)
    for out in (OUT_GIF, OUT_WEBM):
        print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
