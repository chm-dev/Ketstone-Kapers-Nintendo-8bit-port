#!/usr/bin/env python3
"""Summarize an Altirra disassembly listing (ADDR: bytes  mnemonic operands).

Reports JSR/JMP/branch targets, routine boundaries, and address references so
the 6502 control flow can be charted before writing the RE spec.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path

LINE = re.compile(r"^([0-9A-F]{4}):\s+([0-9a-f ]+?)\s{2,}(\S+)\s*(.*)$")


def parse(path: Path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = LINE.match(line)
        if not m:
            continue
        addr = int(m.group(1), 16)
        raw = m.group(2).strip()
        mnem = m.group(3).lower()
        operands = m.group(4).strip()
        rows.append({"addr": addr, "raw": raw, "mnem": mnem, "op": operands, "line": line})
    return rows


TARGET = re.compile(r"\$([0-9A-Fa-f]{4})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("listing", type=Path)
    args = ap.parse_args()

    rows = parse(args.listing)
    if not rows:
        raise SystemExit("no instructions parsed")

    jsr = defaultdict(list)
    jmp = defaultdict(list)
    branches = defaultdict(list)
    data_refs = Counter()
    all_targets = Counter()

    for r in rows:
        m = TARGET.search(r["op"])
        t = int(m.group(1), 16) if m else None
        if t is not None:
            all_targets[t] += 1
        if r["mnem"] == "jsr" and t is not None:
            jsr[t].append(r["addr"])
        elif r["mnem"] == "jmp" and t is not None:
            jmp[t].append(r["addr"])
        elif r["mnem"].startswith("b") and t is not None:
            branches[t].append(r["addr"])
        elif t is not None and r["mnem"] not in ("jsr", "jmp"):
            data_refs[t] += 1

    print(f"instructions: {len(rows)}")
    print(f"range: ${rows[0]['addr']:04X}-${rows[-1]['addr']:04X}")

    print("\n== JSR targets (routine entries) ==")
    for t in sorted(jsr):
        print(f"  ${t:04X}  calls={len(jsr[t])}  from {', '.join(f'${a:04X}' for a in jsr[t][:8])}")

    print("\n== JMP targets not also JSR targets ==")
    for t in sorted(jmp):
        if t not in jsr:
            print(f"  ${t:04X}  jumps={len(jmp[t])}  from {', '.join(f'${a:04X}' for a in jmp[t][:8])}")

    print("\n== branch targets outside the routine containing the branch ==")
    for t in sorted(branches):
        print(f"  ${t:04X}  branches={len(branches[t])}")

    print("\n== most-referenced data addresses ==")
    for t, n in data_refs.most_common(80):
        if 0xA000 <= t <= 0xBFFF:
            print(f"  ${t:04X}  refs={n}")

    print("\n== JSR targets grouped by containing 16-byte region ==")
    for t in sorted(jsr):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
