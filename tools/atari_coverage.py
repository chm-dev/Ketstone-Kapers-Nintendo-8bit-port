#!/usr/bin/env python3
"""Execution coverage of the Keystone Kapers cart from the Altirra profiler.

Boots the XEX, runs attract, presses START, plays a scripted input timeline with the
instruction profiler on, and writes every executed PC (cart range) to
assets/atari/runtime/coverage.txt (one hex address per line) for `rdis.py --entries-file`.

Usage: python tools/atari_coverage.py [--frames 1500] [--token PATH]
"""
import argparse, json, sys, tempfile
from pathlib import Path

SDK = Path(r"F:\Emu\Atari800\Altirra\AlitrraBridge\sdk\python")
sys.path.insert(0, str(SDK))
from altirra_bridge import AltirraBridge  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def newest_token():
    c = sorted(Path(tempfile.gettempdir()).glob("altirra-bridge-*.token"), key=lambda p: p.stat().st_mtime)
    if not c:
        raise SystemExit("no token; start AltirraBridgeServer.exe (stdout/stderr redirected to files)")
    return c[-1]


def step(a, n):
    a.frame(n)
    a.clock()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token")
    ap.add_argument("--xex", default=str(ROOT / "xex" / "Keystone_Kapers.xex"))
    ap.add_argument("--out", default=str(ROOT / "assets/atari/runtime/coverage.txt"))
    ap.add_argument("--raw", default=str(ROOT / "assets/atari/runtime/profile_raw.json"))
    a_ = ap.parse_args()
    a = AltirraBridge.from_token_file(a_.token or str(newest_token()))
    a.config("video", "ntsc")
    a.fresh()
    a.boot(a_.xex)
    step(a, 320)
    a.profile_start(mode="insns")
    step(a, 600)  # attract
    a.consol(start=True); step(a, 2); a.consol(); step(a, 30)
    timeline = ["right", "right", "up", "right", "left", "down", "left", "up", "right", "right"]
    for i, d in enumerate(timeline * 6):
        a.joy(0, d, fire=(i % 3 == 0))
        step(a, 60)
    a.joy(0, "centre", fire=False)
    a.profile_stop()
    rep = a.profile_dump(top=100000)
    Path(a_.raw).write_text(json.dumps(rep, indent=1, default=str))
    print(type(rep), (list(rep)[:5] if isinstance(rep, dict) else rep[:3]))


if __name__ == "__main__":
    main()
