#!/usr/bin/env python3
"""Change-log of RAM bytes under an input plan (same plan syntax as atari_trace.py).

    python tools/atari_events.py --plan centre:3000 --ranges 1B-1F,21,25-28,30-3B,71-78,85-88
Prints `frame addr old->new` per change; optionally `--quiet` ignores listed addrs.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"F:\Emu\Atari800\Altirra\AlitrraBridge\sdk\python")
from altirra_bridge import AltirraBridge  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def newest_token() -> Path:
    c = sorted(Path(tempfile.gettempdir()).glob("altirra-bridge-*.token"), key=lambda p: p.stat().st_mtime)
    return c[-1]


def parse_ranges(s):
    out = []
    for part in s.split(","):
        lo, _, hi = part.partition("-")
        out += range(int(lo, 16), int(hi or lo, 16) + 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--ranges", required=True)
    ap.add_argument("--ignore", default="")
    ap.add_argument("--settle", type=int, default=600)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--poke", default="", help="ADDR=VAL[,ADDR=VAL] hex, applied after the settle")
    ap.add_argument("--shots", default="", help="comma list of frames to screenshot")
    ap.add_argument("--outdir", type=Path, default=ROOT / "assets/atari/runtime/events")
    args = ap.parse_args()
    addrs = parse_ranges(args.ranges)
    ign = set(parse_ranges(args.ignore)) if args.ignore else set()
    addrs = [x for x in addrs if x not in ign]
    shots = {int(x) for x in args.shots.split(",") if x}
    if shots:
        args.outdir.mkdir(parents=True, exist_ok=True)

    a = AltirraBridge.from_token_file(str(newest_token()))
    a.config("video", "ntsc")
    a.fresh()
    a.boot(str(ROOT / "xex/Keystone_Kapers.xex"))
    a.frame(320); a.clock()
    a.consol(start=True); a.frame(2); a.clock(); a.consol()
    a.frame(args.settle); a.clock()

    for kv in filter(None, args.poke.split(",")):
        k, _, v = kv.partition("=")
        a.poke(int(k, 16), int(v, 16))
    prev = a.memdump(0, 0x200)
    f = 0
    for item in args.plan.split(","):
        spec, _, n = item.partition(":")
        d, _, fire = spec.partition("+")
        a.joy(0, "centre" if d in ("", "fire") else d, fire=(d == "fire" or bool(fire)))
        for _ in range(int(n)):
            a.frame(1); a.clock()
            if f % args.stride == 0:
                m = a.memdump(0, 0x200)
                ch = [f"{x:02X}:{prev[x]:02X}>{m[x]:02X}" for x in addrs if m[x] != prev[x]]
                if ch:
                    print(f"{f:5d} {spec:10s} " + " ".join(ch))
                prev = m
            if f in shots:
                a.screenshot(path=str(args.outdir / f"f{f:05d}.png"))
            f += 1
    a.joy(0, "centre", fire=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
