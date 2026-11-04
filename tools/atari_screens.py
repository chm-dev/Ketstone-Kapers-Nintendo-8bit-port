#!/usr/bin/env python3
"""Walk left through all 8 screens, grab a screenshot every N frames with game state,
then composite a per-pixel mode image per screen index (removes moving sprites).

    python tools/atari_screens.py --step 5 --outdir assets/atari/runtime/screens
Writes shots/NNNN.png, shots.csv (frame,screen,x2c,floor), then screen_K.png (mode composite).
"""
from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"F:\Emu\Atari800\Altirra\AlitrraBridge\sdk\python")
from altirra_bridge import AltirraBridge  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def newest_token() -> Path:
    c = sorted(Path(tempfile.gettempdir()).glob("altirra-bridge-*.token"), key=lambda p: p.stat().st_mtime)
    return c[-1]


def run(a, n):
    a.frame(n)
    a.clock()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, default=5)
    ap.add_argument("--frames", type=int, default=1400)
    ap.add_argument("--outdir", type=Path, default=ROOT / "assets/atari/runtime/screens")
    ap.add_argument("--composite-only", action="store_true")
    args = ap.parse_args()
    shots = args.outdir / "shots"
    shots.mkdir(parents=True, exist_ok=True)

    if not args.composite_only:
        a = AltirraBridge.from_token_file(str(newest_token()))
        a.config("video", "ntsc")
        a.fresh()
        a.boot(str(ROOT / "xex/Keystone_Kapers.xex"))
        run(a, 320)
        a.consol(start=True)
        run(a, 2)
        a.consol()
        run(a, 600)
        a.joy(0, "left")
        rows = []
        for f in range(0, args.frames, args.step):
            run(a, args.step)
            m = a.memdump(0, 0x100)
            a.screenshot(path=str(shots / f"{f:04d}.png"))
            rows.append((f, m[0x1E], m[0x2C], m[0x1D] >> 3))
        a.joy(0, "centre")
        with open(args.outdir / "shots.csv", "w", newline="") as fh:
            csv.writer(fh).writerows([("frame", "screen", "x2c", "floor")] + rows)

    by_screen: dict[int, list[Path]] = {}
    with open(args.outdir / "shots.csv") as fh:
        for r in list(csv.reader(fh))[1:]:
            by_screen.setdefault(int(r[1]), []).append(shots / f"{int(r[0]):04d}.png")
    for s, files in sorted(by_screen.items()):
        ims = [Image.open(p).convert("RGB") for p in files]
        w, h = ims[0].size
        out = Image.new("RGB", (w, h))
        px = [im.load() for im in ims]
        po = out.load()
        for y in range(h):
            for x in range(w):
                po[x, y] = Counter(p[x, y] for p in px).most_common(1)[0][0]
        out.save(args.outdir / f"screen_{s}.png")
        print(f"screen {s}: {len(files)} shots, size {w}x{h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
