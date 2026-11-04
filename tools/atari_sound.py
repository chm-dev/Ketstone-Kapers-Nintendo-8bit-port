#!/usr/bin/env python3
"""Log POKEY register changes per frame under an input plan (plan syntax as atari_trace.py).

    python tools/atari_sound.py --plan fire:40 --regs AUDF1,AUDC1 --out assets/atari/runtime/sound/jump.txt
Each line: frame  $17 $12 | reg=val ... (only changed regs). Sampled once per frame, so only the last write
per frame is visible (the game writes each channel at most once per frame).
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"F:\Emu\Atari800\Altirra\AlitrraBridge\sdk\python")
from altirra_bridge import AltirraBridge  # noqa: E402


def newest_token() -> Path:
    c = sorted(Path(tempfile.gettempdir()).glob("altirra-bridge-*.token"), key=lambda p: p.stat().st_mtime)
    return c[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--regs", default="AUDF1,AUDC1,AUDF2,AUDC2,AUDF3,AUDC3,AUDF4,AUDC4,AUDCTL")
    ap.add_argument("--settle", type=int, default=600)
    ap.add_argument("--from-boot", action="store_true", help="log from the start of boot (frame 0)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--poke", default="", help="ADDR=VAL[,ADDR=VAL] hex, applied right after the settle")
    args = ap.parse_args()
    regs = args.regs.split(",")

    a = AltirraBridge.from_token_file(str(newest_token()))
    a.config("video", "ntsc")
    a.fresh()
    a.boot(str(Path(__file__).resolve().parent.parent / "xex/Keystone_Kapers.xex"))
    lines = []
    prev = {}
    f = 0

    def step(label):
        nonlocal prev, f
        a.frame(1); a.clock()
        p = a.pokey()
        m = a.memdump(0x10, 0x10)
        cur = {r: p[r] for r in regs}
        ch = [f"{r}={cur[r][1:]}" for r in regs if prev.get(r) != cur[r]]
        if ch:
            lines.append(f"{f:5d} {label:8s} id={m[7]:02X} st={m[2]:02X} | " + " ".join(ch))
        prev = cur
        f += 1

    if args.from_boot:
        for _ in range(320):
            step("boot")
    else:
        a.frame(320); a.clock()
    a.consol(start=True); a.frame(2); a.clock(); a.consol()
    if not args.from_boot:
        a.frame(args.settle); a.clock()
    f = 0
    for kv in filter(None, args.poke.split(",")):
        k, _, v = kv.partition("=")
        a.poke(int(k, 16), int(v, 16))
    for item in args.plan.split(","):
        spec, _, n = item.partition(":")
        d, _, fire = spec.partition("+")
        a.joy(0, "centre" if d in ("", "fire") else d, fire=(d == "fire" or bool(fire)))
        for _ in range(int(n)):
            step(spec)
    a.joy(0, "centre", fire=False)
    text = "\n".join(lines)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
