#!/usr/bin/env python3
"""Post-process the raw VHS recording of skill-demo.tape.

    python assets/demo/skill-demo-post.py /tmp/openosint-demo-raw/raw.mp4 \
        --deny you@example.com --deny yourname

What it does:
  1. Splits the video into frames.
  2. Masks the Claude Code header (logo, version, plan) that stays on screen after /clear.
  3. Speeds up idle frames (model thinking); typing and the report burst stay at 1x.
  4. Holds the final frame, then writes skill-demo.mp4 (H.264) and skill-demo.gif.
  5. OCRs every distinct output frame and fails on private strings (needs tesseract).

Needs: ffmpeg, gifsicle, tesseract, and `pip install numpy pillow`.
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

FPS = 15
QUIET_SPEED = 4          # keep 1 of every N idle frames
BUSY_WINDOW = 7          # frames either side
BUSY_PX = 8000           # summed changed pixels in the window that count as "busy"
CHANGE_PX = 2000         # a frame change above this is real content (not cursor/spinner)
PIXEL_DELTA = 20
LOGO_MIN_ROW_PX = 12     # orange pixels per row that mark a logo row
LOGO_X = slice(40, 150)  # skip the left margin, where the spinner glyph lives
HEADER_X = slice(10, 520)
WINDOW_BAR_PX = 45
GIF_COLORS = 64
GIF_LOSSY = 60
DEFAULT_DENY = ("/Users/", "/home/", "sk-ant", "Bearer ", "Sonnet 5", "Claude Pro", "Claude Max")


def run(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def load_frames(raw: Path, workdir: Path) -> list[Path]:
    frames = workdir / "raw"
    frames.mkdir()
    run("ffmpeg", "-v", "error", "-i", str(raw), "-vf", f"fps={FPS}", str(frames / "%05d.png"))
    return sorted(frames.glob("*.png"))


def change_counts(frames: list[Path]) -> list[int]:
    counts, prev = [], None
    for f in frames:
        gray = np.asarray(Image.open(f).convert("L"), dtype=np.int16)
        counts.append(0 if prev is None else int((abs(gray - prev) > PIXEL_DELTA).sum()))
        prev = gray
    return counts


def pick_frames(counts: list[int]) -> list[int]:
    """Indices to keep: busy stretches at 1x, idle stretches at 1/QUIET_SPEED."""
    last = max(i for i, c in enumerate(counts) if c > CHANGE_PX)
    kept, idle_run = [], 0
    for i in range(last + 1):
        window = sum(counts[max(0, i - BUSY_WINDOW):i + BUSY_WINDOW + 1])
        if window > BUSY_PX or i == 0:
            kept.append(i)
            idle_run = 0
            continue
        if idle_run % QUIET_SPEED == 0:
            kept.append(i)
        idle_run += 1
    return kept


def mask_header(img: np.ndarray) -> tuple[np.ndarray, bool]:
    """Paint over the Claude orange logo and the version/plan text beside it."""
    region = img[:, LOGO_X].astype(int)
    orange = (
        (region[..., 0] > 180)
        & (region[..., 1] > 90) & (region[..., 1] < 150)
        & (region[..., 2] > 60) & (region[..., 2] < 110)
    )
    orange[:WINDOW_BAR_PX] = False
    rows = np.where(orange.sum(axis=1) > LOGO_MIN_ROW_PX)[0]
    if len(rows) == 0:
        return img, False
    top, bottom = max(rows.min() - 10, WINDOW_BAR_PX), rows.max() + 26
    background = np.median(img[top:bottom, 700:800].reshape(-1, 3), axis=0).astype(np.uint8)
    masked = img.copy()
    masked[top:bottom, HEADER_X] = background
    return masked, True


def write_frames(frames: list[Path], kept: list[int], hold_s: float, out: Path) -> int:
    out.mkdir()
    n = 0
    for i in kept:
        n += 1
        masked, _ = mask_header(np.asarray(Image.open(frames[i]).convert("RGB")))
        Image.fromarray(masked).save(out / f"{n:05d}.png")
    last = out / f"{n:05d}.png"
    for _ in range(int(hold_s * FPS)):
        n += 1
        shutil.copy(last, out / f"{n:05d}.png")
    return n


def encode(frames_dir: Path, mp4: Path, gif: Path, workdir: Path) -> None:
    pattern = str(frames_dir / "%05d.png")
    run("ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", pattern,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(mp4))
    palette, raw_gif = workdir / "pal.png", workdir / "raw.gif"
    run("ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", pattern,
        "-vf", f"palettegen=max_colors={GIF_COLORS}:stats_mode=diff", str(palette))
    run("ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", pattern, "-i", str(palette),
        "-lavfi", "paletteuse=dither=none:diff_mode=rectangle", "-loop", "0", str(raw_gif))
    run("gifsicle", "-O3", f"--lossy={GIF_LOSSY}", str(raw_gif), "-o", str(gif))


def ocr_text(frame: Path) -> str:
    img = ImageOps.invert(Image.open(frame).convert("L"))
    img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    scaled = frame.with_suffix(".ocr.png")
    img.save(scaled)
    result = subprocess.run(["tesseract", str(scaled), "stdout", "--psm", "6"], capture_output=True)
    scaled.unlink()
    return result.stdout.decode("utf-8", "replace")


def scan_for_private_strings(frames_dir: Path, deny: list[str]) -> list[str]:
    distinct, prev = [], None
    for f in sorted(frames_dir.glob("[0-9]*.png")):
        gray = np.asarray(Image.open(f).convert("L"), dtype=np.int16)
        if prev is None or (abs(gray - prev) > PIXEL_DELTA).sum() >= 200:
            distinct.append(f)
            prev = gray
    with ThreadPoolExecutor(6) as pool:
        texts = list(pool.map(ocr_text, distinct))
    patterns = [re.compile(re.escape(d), re.IGNORECASE) for d in deny]
    hits = [f"{f.name}: {p.pattern}" for f, t in zip(distinct, texts) for p in patterns if p.search(t)]
    print(f"OCR scanned {len(distinct)} distinct frames")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw", type=Path, help="raw video written by skill-demo.tape")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent, help="where skill-demo.mp4/.gif go")
    ap.add_argument("--hold", type=float, default=3.0, help="seconds to hold the final frame")
    ap.add_argument("--deny", action="append", default=[], help="extra string that must not appear (email, username)")
    ap.add_argument("--no-ocr", action="store_true", help="skip the privacy scan (not for publishing)")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="skill-demo-") as tmp:
        work = Path(tmp)
        frames = load_frames(args.raw, work)
        kept = pick_frames(change_counts(frames))
        total = write_frames(frames, kept, args.hold, work / "out")
        print(f"{len(frames) / FPS:.1f}s raw -> {total / FPS:.1f}s ({total} frames)")
        if not args.no_ocr:
            hits = scan_for_private_strings(work / "out", [*DEFAULT_DENY, *args.deny])
            if hits:
                print("PRIVATE STRINGS FOUND, nothing written:", *hits, sep="\n  ")
                return 1
        encode(work / "out", args.out / "skill-demo.mp4", args.out / "skill-demo.gif", work)
    print(f"wrote {args.out / 'skill-demo.mp4'} and {args.out / 'skill-demo.gif'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
