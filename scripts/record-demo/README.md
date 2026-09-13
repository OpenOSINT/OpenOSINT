# OpenOSINT — Demo Recording Pipeline

Reproduces `docs/assets/demo-web-graph.{gif,mp4,png}` from a clean checkout in one command.

## Prerequisites

| Tool | Install |
|------|---------|
| Node 18+ | https://nodejs.org |
| ffmpeg | `brew install ffmpeg` |
| gifski | `brew install gifski` |
| Anthropic API key | Set as `OPENOSINT_DEMO_KEY` env var |

## Full pipeline (from clean checkout)

```bash
# 1. Install Python deps (if not already)
pip install -e ".[dev]"

# 2. Install Node recorder deps + Playwright Chromium
cd scripts/record-demo && npm install && npx playwright install chromium && cd ../..

# 3. Start the web server in one terminal
openosint web

# 4. In another terminal, set key and run
export OPENOSINT_DEMO_KEY=sk-ant-api03-...   # your Anthropic key — never committed
make demo
```

`make demo` runs `record.mjs` then `encode.sh` and writes the three committed assets.

## What the recording does

1. Opens `http://localhost:8080` in headed Chromium (1440×860 @2x).
2. Seeds `sessionStorage.openosint_byok` via `addInitScript` before first navigation — the key never appears in logs or on screen.
3. Waits for `window._agentLoopReady === true` (ES module bridge ready).
4. Sends `"Investigate openosint.tech"` via Enter on `#chat-input`.
5. Waits for 6+ graph nodes (real DOM/graph state — no fixed sleeps for LLM timing).
6. Waits 1700ms for the Cytoscape layout to settle (debounce 400ms + animate 300ms + buffer 1000ms).
7. Performs a **real mouse click** on the first non-root node (via `renderedPosition()` → `page.mouse.click`) so the cursor is visible on camera.
8. Waits for 9+ nodes (post-pivot expansion) or 20s graceful timeout.
9. Holds final state 2.5s, takes poster screenshot.
10. Closes context — Playwright writes `out/raw.webm`.

## Target: `openosint.tech`

The canonical demo target is our own domain. This ensures:
- No third-party WHOIS/DNS/cert data committed into the README forever.
- The recording is reproducible (our domain's records are stable).
- The demo doubles as marketing for our own product.

## Encoding pipeline (`encode.sh`)

```
raw.webm  ->  MP4 (H.264, crf18, faststart)
          ->  PNG frames at native 1440x860 (NO ffmpeg scale filter)
          ->  GIF via gifski (the only downscaler)
```

gifski fallback order if GIF exceeds 10 MB:

| Attempt | fps | width | quality |
|---------|-----|-------|---------|
| 1 (primary) | 15 | 1440px | 90 |
| 2 | 12 | 1440px | 80 |
| 3 | 12 | 1200px | 75 |
| 4 | 10 | 1000px | 65 |
| fail | — | — | abort with size report |

## Secrets discipline

- `OPENOSINT_DEMO_KEY` is read once into a `const` and passed only to `addInitScript`.
- It is **never** interpolated into log strings, file paths, or recorded frames.
- `scripts/record-demo/out/` is gitignored (raw webm and frame PNGs never committed).
- The browser sessionStorage is tab-session-only and never leaves the browser process.

## Overriding defaults

```bash
OPENOSINT_DEMO_URL=https://demo.openosint.tech \
OPENOSINT_PROVIDER=anthropic \
OPENOSINT_MODEL=claude-opus-4-8 \
make demo
```

## Toolchain check (no key needed)

```bash
node scripts/record-demo/record.mjs --check
```

Verifies playwright is importable. Exits 0 if satisfied.
