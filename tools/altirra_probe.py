#!/usr/bin/env python3
"""AltirraBridge probe for the Keystone Kapers Atari source binary.

Thin, repeatable CLI over the Altirra Python SDK. Every subcommand boots the
reference XEX unless --no-boot is given, advances a deterministic number of
frames, and then captures state.

Examples:
    python tools/altirra_probe.py disasm --start 0xA000 --end 0xB2A4 --out docs/atari_disasm.txt
    python tools/altirra_probe.py capture --frames 300 --outdir assets/atari/runtime/boot
    python tools/altirra_probe.py profile --frames 600 --mode insns --top 40
    python tools/altirra_probe.py memdump --start 0x0000 --length 0x10000 --out ram.bin
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
import time
from pathlib import Path

SDK = Path(r"F:\Emu\Atari800\Altirra\AlitrraBridge\sdk\python")
if str(SDK) not in sys.path:
    sys.path.insert(0, str(SDK))

from altirra_bridge import AltirraBridge  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XEX = ROOT / "xex" / "Keystone_Kapers.xex"


def newest_token() -> Path:
    pattern = "altirra-bridge-*.token"
    candidates = sorted(Path(tempfile.gettempdir()).glob(pattern), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise SystemExit("no altirra-bridge-*.token found; start AltirraBridgeServer first")
    return candidates[-1]


def connect(token: str | None) -> AltirraBridge:
    path = Path(token) if token else newest_token()
    if not path.exists():
        raise SystemExit(f"token file not found: {path}")
    return AltirraBridge.from_token_file(str(path))


def barrier(a: AltirraBridge, frames: int) -> None:
    """Frame gate: frame(n) returns immediately, the next command waits."""
    if frames > 0:
        a.frame(frames)
        a.clock()


def prepare(a: AltirraBridge, args) -> None:
    if getattr(args, "fresh", False):
        a.fresh()
    if getattr(args, "video", None):
        a.config("video", args.video)
    if not getattr(args, "no_boot", False):
        a.boot(str(args.xex))
        barrier(a, args.boot_frames)


def hexlist(data: bytes) -> list[str]:
    return [f"{b:02x}" for b in data]


def parse_int(text: str) -> int:
    return int(text, 0)


def cmd_info(a: AltirraBridge, args) -> int:
    print(json.dumps({"ping": a.ping(), "config": a.config(), "regs": a.regs()}, indent=2))
    return 0


def parse_addr(value) -> int:
    text = str(value)
    return int(text.lstrip("$"), 16) if text.startswith("$") else int(text, 0)


def cmd_disasm(a: AltirraBridge, args) -> int:
    start = parse_int(args.start)
    end = parse_int(args.end)
    out = Path(args.out) if args.out else None
    lines: list[str] = []

    addr = start
    while addr <= end:
        chunk = a.disasm(addr, min(64, end - addr + 1))
        if not chunk:
            break
        advanced = False
        for item in chunk:
            item_addr = parse_addr(item["addr"])
            if item_addr > end:
                break
            raw = item.get("bytes", "")
            if isinstance(raw, list):
                raw = " ".join(f"{b:02x}" if isinstance(b, int) else str(b) for b in raw)
            lines.append(f"{item_addr:04X}: {raw:<9} {item['text']}")
            nxt = parse_addr(item["next"]) if item.get("next") is not None else item_addr + 1
            if nxt <= item_addr:
                nxt = item_addr + 1
            addr = nxt
            advanced = True
        if not advanced:
            break

    text = "\n".join(lines) + "\n"
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {len(lines)} instructions to {out}")
    else:
        print(text)
    return 0


def capture_payload(a: AltirraBridge) -> dict:
    return {
        "timestamp": time.time(),
        "regs": a.regs(),
        "hwstate": a.hwstate(),
        "antic": a.antic(),
        "gtia": a.gtia(),
        "pmg": a.pmg(),
        "pokey": a.pokey(),
        "pia": a.pia(),
        "dlist": a.dlist(),
        "palette_hex": a.palette().hex(),
        "cart_info": a.cart_info(),
    }


def cmd_capture(a: AltirraBridge, args) -> int:
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    payload = capture_payload(a)
    (outdir / "state.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    a.screenshot(path=str(outdir / "screen.png"))
    if args.dump_ram:
        ram = a.memdump(0x0000, 0x10000)
        (outdir / "ram_0000_ffff.bin").write_bytes(ram)
        print(f"RAM dump: {len(ram)} bytes")
    print(f"captured {outdir}")
    return 0


def cmd_memdump(a: AltirraBridge, args) -> int:
    start = parse_int(args.start)
    length = parse_int(args.length)
    data = a.memdump(start, length)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"wrote {len(data)} bytes @ 0x{start:04X} -> {out}")
    return 0


def cmd_profile(a: AltirraBridge, args) -> int:
    a.profile_start(mode=args.mode)
    barrier(a, args.frames)
    a.profile_stop()
    dump = a.profile_dump(top=args.top)
    text = json.dumps(dump, indent=2, default=str) if not isinstance(dump, str) else dump
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote profile to {args.out}")
    else:
        print(text)
    if args.tree:
        tree = a.profile_dump_tree()
        print(json.dumps(tree, indent=2, default=str) if not isinstance(tree, str) else tree)
    return 0


def cmd_memsearch(a: AltirraBridge, args) -> int:
    data = bytes.fromhex(args.hex)
    hits = a.memsearch(data, parse_int(args.start), parse_int(args.end))
    print(json.dumps(hits, indent=2, default=str))
    return 0


def cmd_input(a: AltirraBridge, args) -> int:
    """Run a small input timeline: 'frames:action' steps, e.g. 120:fire 60:none."""
    try:
        for step in args.steps:
            frames_s, _, action = step.partition(":")
            if action == "fire":
                a.joy(0, "centre", fire=True)
            elif action == "none":
                a.joy(0, "centre", fire=False)
            elif action in ("up", "down", "left", "right"):
                a.joy(0, action, fire=False)
            elif action == "start":
                a.consol(start=True)
            elif action == "select":
                a.consol(select=True)
            elif action == "release":
                a.consol()
            else:
                raise SystemExit(f"unknown action: {action}")
            barrier(a, int(frames_s))
    finally:
        a.joy(0, "centre", fire=False)
        a.consol()
    print("input timeline complete; regs:", a.regs())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--token", help="token file (default: newest altirra-bridge-*.token)")
    parser.add_argument("--xex", type=Path, default=DEFAULT_XEX)
    parser.add_argument("--video", default="ntsc")
    parser.add_argument("--fresh", action="store_true", help="factory reset before booting")
    parser.add_argument("--no-boot", action="store_true", help="use the already-loaded image")
    parser.add_argument("--boot-frames", type=int, default=300)

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("info")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("disasm")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--out")
    p.set_defaults(func=cmd_disasm)

    p = sub.add_parser("capture")
    p.add_argument("--frames", type=int, default=300)
    p.add_argument("--outdir", required=True)
    p.add_argument("--dump-ram", action="store_true")
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("memdump")
    p.add_argument("--start", required=True)
    p.add_argument("--length", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_memdump)

    p = sub.add_parser("profile")
    p.add_argument("--frames", type=int, default=600)
    p.add_argument("--mode", default="insns")
    p.add_argument("--top", type=int, default=40)
    p.add_argument("--tree", action="store_true")
    p.add_argument("--out")
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("memsearch")
    p.add_argument("--hex", required=True)
    p.add_argument("--start", default="0x0000")
    p.add_argument("--end", default="0xC000")
    p.set_defaults(func=cmd_memsearch)

    p = sub.add_parser("input")
    p.add_argument("--after", type=int, default=300, help="frames to advance before input")
    p.add_argument("--steps", nargs="+", required=True)
    p.set_defaults(func=cmd_input)

    args = parser.parse_args()
    if not args.xex.exists():
        raise SystemExit(f"XEX not found: {args.xex}")

    with connect(args.token) as a:
        prepare(a, args)
        if args.command not in ("disasm", "capture", "memdump", "profile", "memsearch", "input"):
            return args.func(a, args)
        if args.command == "input":
            barrier(a, args.after)
        return args.func(a, args)


if __name__ == "__main__":
    raise SystemExit(main())
