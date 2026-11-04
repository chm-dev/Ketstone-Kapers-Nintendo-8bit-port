#!/usr/bin/env python3
"""Force time-outs (poke $28=1 whenever it is above $05) and log life/state changes until game over.
    python tools/atari_lives.py --frames 4000
"""
import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"F:\Emu\Atari800\Altirra\AlitrraBridge\sdk\python")
from altirra_bridge import AltirraBridge  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--frames", type=int, default=4000)
ap.add_argument("--watch", default="03,13,14,15,17,21,22,25,26,27,28,29,93,9E,23,0B,05")
ap.add_argument("--outdir", type=Path, default=ROOT / "assets/atari/runtime/lives")
args = ap.parse_args()
watch = [int(x, 16) for x in args.watch.split(",")]
tok = sorted(Path(tempfile.gettempdir()).glob("altirra-bridge-*.token"), key=lambda p: p.stat().st_mtime)[-1]
a = AltirraBridge.from_token_file(str(tok))
a.config("video", "ntsc")
a.fresh()
a.boot(str(ROOT / "xex/Keystone_Kapers.xex"))
a.frame(320); a.clock()
a.consol(start=True); a.frame(2); a.clock(); a.consol()
a.frame(600); a.clock()
args.outdir.mkdir(parents=True, exist_ok=True)
prev = a.memdump(0, 0x200)
for f in range(args.frames):
    a.frame(1); a.clock()
    m = a.memdump(0, 0x200)
    ch = [f"{x:02X}:{prev[x]:02X}>{m[x]:02X}" for x in watch if m[x] != prev[x]]
    if ch:
        print(f"{f:5d} " + " ".join(ch))
    if m[0x28] > 0x05 and m[0x14] & 0x80:
        a.poke(0x28, 0x01)
    if f % 400 == 0:
        a.screenshot(path=str(args.outdir / f"f{f:05d}.png"))
    prev = m
a.screenshot(path=str(args.outdir / "end.png"))
