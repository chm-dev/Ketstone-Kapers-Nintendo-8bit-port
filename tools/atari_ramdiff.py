#!/usr/bin/env python3
"""Per-input RAM diff: boot, START, then for each input hold it N frames and
report which zero-page / stack bytes changed (first -> last value, change count).

    python tools/atari_ramdiff.py --inputs centre right left up down fire
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

SDK = Path(r"F:\Emu\Atari800\Altirra\AlitrraBridge\sdk\python")
sys.path.insert(0, str(SDK))
from altirra_bridge import AltirraBridge  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
XEX = ROOT / "xex" / "Keystone_Kapers.xex"


def newest_token() -> Path:
    c = sorted(Path(tempfile.gettempdir()).glob("altirra-bridge-*.token"), key=lambda p: p.stat().st_mtime)
    if not c:
        raise SystemExit("no token")
    return c[-1]


def run(a, n):
    a.frame(n)
    a.clock()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", default=["centre", "right", "left", "up", "down", "fire"])
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--step", type=int, default=4)
    ap.add_argument("--settle", type=int, default=120, help="frames after START before probing")
    args = ap.parse_args()

    a = AltirraBridge.from_token_file(str(newest_token()))
    a.config("video", "ntsc")
    a.fresh()
    a.boot(str(XEX))
    run(a, 320)
    a.consol(start=True)
    run(a, 2)
    a.consol()
    run(a, args.settle)

    for inp in args.inputs:
        with a.checkpoint():
            if inp == "fire":
                a.joy(0, "centre", fire=True)
            else:
                a.joy(0, inp)
            snaps = []
            for _ in range(args.frames // args.step):
                run(a, args.step)
                snaps.append(a.memdump(0x0000, 0x200))
            a.joy(0, "centre", fire=False)
        print(f"== {inp} ({args.frames} frames, every {args.step}) ==")
        for addr in range(0x200):
            seq = [s[addr] for s in snaps]
            ch = sum(1 for x, y in zip(seq, seq[1:]) if x != y)
            if ch:
                print(f"  ${addr:03X} changes={ch:3d} first={seq[0]:02X} last={seq[-1]:02X} "
                      f"min={min(seq):02X} max={max(seq):02X}")
    a.joy(0, "centre", fire=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
