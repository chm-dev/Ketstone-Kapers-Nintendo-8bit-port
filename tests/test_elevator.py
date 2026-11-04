#!/usr/bin/env python3
"""python -I tests/test_elevator.py <golden> "<plan>" --init=...  (golden cols: 90,8F,8E,6B,2C,2D,2E,1D,1E,1C,20,0C,19,2B)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from kk_model import Kop, Thief, parse_plan  # noqa: E402

argv = [a for a in sys.argv[1:] if not a.startswith("--")]
k = Kop()
th = Thief()
for a in sys.argv[1:]:
    if a.startswith("--init="):
        for kv in a[7:].split(","):
            n, v = kv.split("=")
            v = int(v, 16)
            if n.startswith("x"):
                k.xs[int(n[1:])] = v
            else:
                setattr(k, n, v)
rows = [[int(x, 16) for x in line.split()[2:]] for line in Path(argv[0]).read_text().splitlines()[1:]]
plan = parse_plan(argv[1])
assert len(plan) == len(rows), (len(plan), len(rows))
prev90 = (rows[0][0] - 1) & 0xFF
bad = 0
for f, ((stick, fire), r) in enumerate(zip(plan, rows)):
    k.step(stick, fire, prev90, r[1])
    prev90 = r[0]
    th.step(r[0], kop_path=k.path, kop_screen=k.screen)
    k.thief_path = th.path
    exp = dict(e8e=r[2], e6b=r[3], x0=r[4], path=r[7], screen=r[8], c1c=r[9], pose=r[10], face=r[11])
    got = dict(e8e=k.e8e, e6b=k.e6b, x0=k.xs[0], path=k.path, screen=k.screen,
               c1c=k.c1c, pose=k.pose, face=k.face)
    if got != exp:
        bad += 1
        if bad <= 10:
            print(f"frame {f}: " + " ".join(f"{n}:{got[n]:02X}!={exp[n]:02X}" for n in exp if got[n] != exp[n]))
print("mismatching frames:", bad, "of", len(rows))
sys.exit(1 if bad else 0)
