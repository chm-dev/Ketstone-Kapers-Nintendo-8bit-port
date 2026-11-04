#!/usr/bin/env python3
"""Per-frame RAM trace under an input timeline, from a fixed post-START checkpoint.

    python tools/atari_trace.py --plan right:40,fire:20,centre:30 --addrs 2C,5D,20
Plan items are `dir[+fire]:frames` (dir = centre/left/right/up/down/...).
--shots N saves screen.png every N frames to --outdir.
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
    if not c:
        raise SystemExit("no token")
    return c[-1]


def run(a, n):
    a.frame(n)
    a.clock()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--addrs", required=True, help="hex addrs, comma separated")
    ap.add_argument("--settle", type=int, default=600)
    ap.add_argument("--pre", type=int, default=0, help="extra frames of centre before plan")
    ap.add_argument("--shots", type=int, default=0)
    ap.add_argument("--poke", default="", help="ADDR=VAL[,ADDR=VAL] hex, applied after the settle")
    ap.add_argument("--outdir", type=Path, default=ROOT / "assets" / "atari" / "runtime" / "trace")
    args = ap.parse_args()
    addrs = [int(x, 16) for x in args.addrs.split(",")]

    a = AltirraBridge.from_token_file(str(newest_token()))
    a.config("video", "ntsc")
    a.fresh()
    a.boot(str(ROOT / "xex" / "Keystone_Kapers.xex"))
    run(a, 320)
    a.consol(start=True)
    run(a, 2)
    a.consol()
    run(a, args.settle + args.pre)
    if args.shots:
        args.outdir.mkdir(parents=True, exist_ok=True)

    for kv in filter(None, args.poke.split(",")):
        k, _, v = kv.partition("=")
        a.poke(int(k, 16), int(v, 16))
    print("frame input  " + " ".join(f"{x:03X}" for x in addrs))
    f = 0
    for item in args.plan.split(","):
        spec, _, n = item.partition(":")
        d, _, fire = spec.partition("+")
        isfire = d == "fire" or bool(fire)
        a.joy(0, "centre" if d in ("", "fire") else d, fire=isfire)
        for _ in range(int(n)):
            run(a, 1)
            m = a.memdump(0, 0x200)
            print(f"{f:4d} {spec:8s} " + " ".join(f"{m[x]:3X}" if False else f"{m[x]:02X} " for x in addrs))
            if args.shots and f % args.shots == 0:
                a.screenshot(path=str(args.outdir / f"f{f:04d}.png"))
            f += 1
    a.joy(0, "centre", fire=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
