#!/usr/bin/env bash
# Regenerates demo.gif and demo.mp4 from demo.tape (single capture, two
# `Output` lines) and re-extracts the review frames.
#
# Requires: vhs, ffmpeg, ffprobe, and `openosint` installed on PATH
# (https://github.com/OpenOSINT/OpenOSINT). Uses `openosint dns example.com`
# — no API key needed.
set -euo pipefail
cd "$(dirname "$0")"

echo "Rendering demo.gif + demo.mp4 via vhs..."
vhs demo.tape

# vhs 0.11.0 ignores `Set Framerate` for GIF output (fixed at 25fps), so
# resample to the spec'd 15fps here.
echo "Resampling to 15fps..."
ffmpeg -y -i demo.gif -vf "fps=15,split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer" -loop 0 demo_15fps.gif
mv demo_15fps.gif demo.gif

echo "Extracting review frames..."
mkdir -p frames
rm -f frames/*.png
ffmpeg -y -i demo.gif -vf "select='eq(n\,3)+eq(n\,15)+eq(n\,35)+eq(n\,90)'" -vsync 0 frames/frame%d.png
mv frames/frame1.png frames/01-prompt.png
mv frames/frame2.png frames/02-typing.png
mv frames/frame3.png frames/03-executing.png
mv frames/frame4.png frames/04-hold.png
python3 -c "
from PIL import Image
im = Image.open('frames/04-hold.png')
im400 = im.resize((400, int(im.size[1]*400/im.size[0])), Image.LANCZOS)
im400.save('frames/04-hold-400px.png')
"

echo "Done."
ls -la demo.gif
ffprobe -v error -select_streams v -show_entries stream=width,height,r_frame_rate,duration -of default=noprint_wrappers=1 demo.gif
