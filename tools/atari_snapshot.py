#!/usr/bin/env python3
"""Boot Keystone Kapers in Altirra, run a scripted input timeline, then snapshot.

Unlike altirra_probe.py this always starts from a clean boot so every capture is
deterministic. Use it to gather runtime evidence for docs/ATARI_RE_SPEC.md:

    python tools/atari_snapshot.py --frames 300 --outdir assets/atari/runtime/attract
    python tools/atari_snapshot.py --start --frames 120 --outdir .../gameplay
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SDK = Path(r"F:\Emu\Atari800\Altirra\AlitrraBridge\sdk\python")
if str(SDK) not in sys.path:
    sys.path.insert(0, str(SDK))

from altirra_bridge import AltirraBridge  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XEX = ROOT / "xex" / "Keystone_Kapers.xex"


def newest_token() -> Path:
    import tempfile

    candidates = sorted(
        Path(tempfile.gettempdir()).glob("altirra-bridge-*.token"),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        raise SystemExit("no altirra-bridge-*.token found; start AltirraBridgeServer first")
    return candidates[-1]


def barrier(a: AltirraBridge, frames: int) -> None:
    if frames > 0:
        a.frame(frames)
        a.clock()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token")
    ap.add_argument("--xex", type=Path, default=DEFAULT_XEX)
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--frames", type=int, default=300, help="frames to run after boot/start")
    ap.add_argument("--start", action="store_true", help="press START before the run")
    ap.add_argument("--select", action="store_true", help="press SELECT before the run")
    ap.add_argument("--hold", default="", help="joystick direction to hold, e.g. left")
    ap.add_argument("--fire", action="store_true", help="hold fire")
    ap.add_argument("--dump", action="append", default=[], help="START:LEN hex range to dump")
    ap.add_argument("--profile-frames", type=int, default=0)
    ap.add_argument("--state-frames", type=int, default=0, help="extra frames before state capture")
    args = ap.parse_args()

    a = AltirraBridge.from_token_file(str(args.token or newest_token()))
    a.config("video", "ntsc")
    a.fresh()
    a.boot(str(args.xex))
    barrier(a, 320)

    if args.start:
        a.consol(start=True)
        barrier(a, 2)
        a.consol()
        barrier(a, 4)
    if args.select:
        a.consol(select=True)
        barrier(a, 2)
        a.consol()
        barrier(a, 4)

    if args.hold or args.fire:
        a.joy(0, args.hold or "centre", fire=args.fire)

    try:
        if args.profile_frames:
            a.profile_start(mode="insns")
            barrier(a, args.profile_frames)
            a.profile_stop()
            prof = a.profile_dump(top=40)
            payload = json.dumps(prof, indent=2, default=str) if not isinstance(prof, str) else prof
            Path(args.outdir).mkdir(parents=True, exist_ok=True)
            (Path(args.outdir) / "profile.json").write_text(payload, encoding="utf-8")
        barrier(a, args.frames)
        barrier(a, args.state_frames)
        outdir = Path(args.outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        state = {
            "timestamp": time.time(),
            "regs": a.regs(),
            "hwstate": a.hwstate(),
            "antic": a.antic(),
            "gtia": a.gtia(),
            "pmg": a.pmg(),
            "pokey": a.pokey(),
            "pia": a.pia(),
            "dlist": a.dlist(),
            "cart_info": a.cart_info(),
        }
        (outdir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        a.screenshot(path=str(outdir / "screen.png"))
        (outdir / "ram_0000_ffff.bin").write_bytes(a.memdump(0x0000, 0x10000))
        for spec in args.dump:
            start_s, _, len_s = spec.partition(":")
            start = int(start_s, 0)
            length = int(len_s, 0) if len_s else 0x100
            (outdir / f"dump_{start:04x}_{length:04x}.bin").write_bytes(
                a.memdump(start, length)
            )
        print(f"captured {outdir} frames={args.frames} regs={a.regs()}")
    finally:
        a.joy(0, "centre", fire=False)
        a.consol()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
