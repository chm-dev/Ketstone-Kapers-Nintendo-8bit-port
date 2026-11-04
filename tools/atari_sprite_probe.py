#!/usr/bin/env python3
"""Sprite / obstacle captures for the RE spec (section 9): screenshot + RAM $0000-$0FFF (zero page,
mirrored shape copies $0300/$0400, PMG players $0C00-$0FFF) at chosen frames of a scripted run.

    python tools/atari_sprite_probe.py --name walk --plan "right:7,cap:w1,right:2,cap:w2"
    python tools/atari_sprite_probe.py --name lvl --poke 22=0B --plan "left:200,cap:a"

Plan items (comma separated):
  dir[+fire]:N   hold joystick for N frames (dir = centre/left/right/up/down/fire...)
  poke:AA=VV     poke a byte (hex) now
  cap:NAME       save <outdir>/<name>/NAME.png + NAME.ram ($0000-$0FFF)
  trace:N:ADDRS  log ADDRS (hex, '/' separated) for N frames of the current input into NAME_trace.txt
--poke applies after the post-START settle (same base state as tools/atari_trace.py).
The NTSC palette (768 B RGB) is written once to <outdir>/palette_ntsc.bin.
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
    ap.add_argument("--name", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--settle", type=int, default=600)
    ap.add_argument("--poke", default="")
    ap.add_argument("--outdir", type=Path, default=ROOT / "assets" / "atari" / "runtime" / "sprites")
    args = ap.parse_args()
    out = args.outdir / args.name
    out.mkdir(parents=True, exist_ok=True)

    a = AltirraBridge.from_token_file(str(newest_token()))
    a.config("video", "ntsc")
    a.fresh()
    a.boot(str(ROOT / "xex" / "Keystone_Kapers.xex"))
    run(a, 320)
    a.consol(start=True)
    run(a, 2)
    a.consol()
    run(a, args.settle)
    pal = args.outdir / "palette_ntsc.bin"
    if not pal.exists():
        pal.write_bytes(bytes(a.palette()))
    for kv in filter(None, args.poke.split(",")):
        k, _, v = kv.partition("=")
        a.poke(int(k, 16), int(v, 16))
    frame = 0
    for item in args.plan.split(","):
        kind, _, rest = item.partition(":")
        if kind == "poke":
            k, _, v = rest.partition("=")
            a.poke(int(k, 16), int(v, 16))
        elif kind == "cap":
            a.screenshot(path=str(out / f"{rest}.png"))
            (out / f"{rest}.ram").write_bytes(bytes(a.memdump(0, 0x1000)))
            print(f"cap {rest} @frame {frame}")
        elif kind == "trace":
            n, _, addrs = rest.partition(":")
            al = [int(x, 16) for x in addrs.split("/")]
            with open(out / "trace.txt", "a") as f:
                f.write("frame " + " ".join(f"{x:03X}" for x in al) + "\n")
                for _ in range(int(n)):
                    run(a, 1)
                    m = a.memdump(0, 0x100)
                    f.write(f"{frame:5d} " + " ".join(f"{m[x]:02X} " for x in al) + "\n")
                    frame += 1
        else:
            d, _, fire = kind.partition("+")
            a.joy(0, "centre" if d in ("", "fire") else d, fire=(d == "fire" or bool(fire)))
            run(a, int(rest))
            frame += int(rest)
    a.joy(0, "centre", fire=False)
    a.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
