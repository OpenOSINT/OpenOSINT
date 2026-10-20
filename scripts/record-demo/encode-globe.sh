#!/usr/bin/env bash
# encode-globe.sh — ffmpeg + gifski encoding pipeline for the GLOBE demo.
#
# Reads:   scripts/record-demo/out/globe-raw.webm
# Writes:  docs/assets/globe-demo.gif  (< 8 MB hard budget)
#          docs/assets/globe-demo.mp4
#
# gifski (not ffmpeg palettegen) does the color quantization — per-frame
# palettes + temporal dithering beat ffmpeg's 256-colour global palette on
# satellite imagery and the atmosphere gradient. ffmpeg only extracts and
# scales frames; gifski never re-scales (scaling happens once, at extraction).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

OUT_DIR="$SCRIPT_DIR/out"
FRAMES_DIR="$OUT_DIR/frames"
ASSETS_DIR="$ROOT/docs/assets"

WEBM="$OUT_DIR/globe-raw.webm"
MP4="$ASSETS_DIR/globe-demo.mp4"
GIF="$ASSETS_DIR/globe-demo.gif"

MAX_GIF_BYTES=$((8 * 1024 * 1024))

for tool in ffmpeg gifski gifsicle; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "ERROR: $tool not found."
    echo "  ffmpeg:   brew install ffmpeg"
    echo "  gifski:   brew install gifski"
    echo "  gifsicle: brew install gifsicle"
    exit 1
  }
done

[ -f "$WEBM" ] || {
  echo "ERROR: $WEBM not found — run record-globe.mjs first."
  exit 1
}

mkdir -p "$ASSETS_DIR" "$FRAMES_DIR"

# ---------------------------------------------------------------------------
# MP4 — H.264, crf 23, yuv420p for compatibility (social posts)
# ---------------------------------------------------------------------------
echo "[*] Encoding MP4..."
# The recorder captures at the browser's own (smaller, reflowed) viewport —
# scale up to the documented 1280x720 output here.
ffmpeg -y -i "$WEBM" -vf "scale=1280:720:flags=lanczos" -c:v libx264 -crf 23 -pix_fmt yuv420p -movflags +faststart "$MP4" \
  2>&1 | grep -E "^(video|frame|Output|error)" || true
MP4_SIZE=$(stat -f%z "$MP4" 2>/dev/null || stat -c%s "$MP4")
echo "[+] MP4: $MP4  ($(( MP4_SIZE / 1024 )) KB)"

# ---------------------------------------------------------------------------
# GIF — extract frames at target fps/width, gifski encodes, gifsicle squeezes.
# Fallback order on the 8 MB budget: fps 15->12, then width 960->800, then
# gifski quality 90->80. Storyboard beats are never cut to hit the budget.
# ---------------------------------------------------------------------------
encode_gif() {
  local fps="$1" width="$2" quality="$3"
  echo "[*] Extracting frames: fps=${fps} width=${width}px..."
  rm -f "$FRAMES_DIR"/f*.png
  ffmpeg -y -i "$WEBM" -vf "fps=${fps},scale=${width}:-1:flags=lanczos" "$FRAMES_DIR/f%05d.png" \
    2>&1 | tail -1
  echo "[*] gifski: quality=${quality}..."
  gifski -o "$GIF" --fps "$fps" --quality "$quality" "$FRAMES_DIR"/f*.png
  gifsicle -O3 "$GIF" -o "$GIF"
  local gif_bytes gif_mb
  gif_bytes=$(stat -f%z "$GIF" 2>/dev/null || stat -c%s "$GIF")
  gif_mb=$(awk "BEGIN {printf \"%.2f\", $gif_bytes/1048576}")
  echo "[i] GIF size: ${gif_mb} MB (${gif_bytes} bytes)"
  [ "$gif_bytes" -le "$MAX_GIF_BYTES" ]
}

FINAL_LABEL="15fps / 960px / q90"
if   encode_gif 15 960 90; then :
elif encode_gif 12 960 90; then FINAL_LABEL="12fps / 960px / q90"; echo "[!] Fallback 1 applied"
elif encode_gif 12 800 90; then FINAL_LABEL="12fps / 800px / q90"; echo "[!] Fallback 2 applied"
elif encode_gif 12 800 80; then FINAL_LABEL="12fps / 800px / q80"; echo "[!] Fallback 3 applied"
else
  GIF_BYTES=$(stat -f%z "$GIF" 2>/dev/null || stat -c%s "$GIF")
  GIF_MB=$(awk "BEGIN {printf \"%.2f\", $GIF_BYTES/1048576}")
  echo ""
  echo "ERROR: GIF is ${GIF_MB} MB after all fallbacks — exceeds the 8 MB budget."
  exit 1
fi

GIF_SIZE=$(stat -f%z "$GIF" 2>/dev/null || stat -c%s "$GIF")
DIMS=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$GIF" 2>/dev/null || echo "unknown")

echo ""
echo "======================================"
echo "  globe demo -> docs/assets/"
echo "--------------------------------------"
printf "  MP4  %6s KB\n" "$(( MP4_SIZE / 1024 ))"
printf "  GIF  %6s KB   %spx   [%s]\n" "$(( GIF_SIZE / 1024 ))" "$DIMS" "$FINAL_LABEL"
echo "======================================"
echo "  Raw frames in $FRAMES_DIR are gitignored."
