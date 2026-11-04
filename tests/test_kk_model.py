#!/usr/bin/env python3
"""Compare tools/kk_model.py with a golden Altirra trace (tools/atari_trace.py output).
    python -I tests/test_kk_model.py <golden.txt> "<plan>" [--old] [--init=screen=7,path=7,x0=B0,x1=..,x2=..,c1c=..]
New golden columns: 90, 8F, 2C, 2D, 1D, 1E, 1C, 20, 0C, 19 [, 2E]; --old (kop_a/kop_b): 90,2C,1D,1E,19,1C,20,0C.
$90/$8F are taken from the trace (jump pace / escalator tick depend on them)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from kk_model import Kop, parse_plan  # noqa: E402

argv = [a for a in sys.argv[1:] if not a.startswith("--")]
old = "--old" in sys.argv
k = Kop()
for a in sys.argv[1:]:
    if a.startswith("--init="):
        for kv in a[7:].split(","):
            n, v = kv.split("=")
            v = int(v, 16)
            if n.startswith("x"):
                k.xs[int(n[1:])] = v
            else:
                setattr(k, {"c1c": "c1c", "screen": "screen", "path": "path"}[n], v)
rows = [[int(x, 16) for x in line.split()[2:]] for line in Path(argv[0]).read_text().splitlines()[1:]]
plan = parse_plan(argv[1])
assert len(plan) == len(rows), (len(plan), len(rows))
prev90 = (rows[0][0] - 1) & 0xFF
bad = 0
for f, ((stick, fire), r) in enumerate(zip(plan, rows)):
    if old:
        c90, c8f = r[0], 0
        exp = dict(x=r[1], path=r[2], screen=r[3], jump=r[4], c1c=r[5], pose=r[6], face=r[7])
        got = dict(x=k.x, path=k.path, screen=k.screen, jump=k.jump, c1c=k.c1c & 0x1F, pose=k.pose, face=k.face)
    else:
        c90, c8f = r[0], r[1]
        exp = dict(x0=r[2], x1=r[3], path=r[4], screen=r[5], c1c=r[6], pose=r[7], face=r[8], jump=r[9])
        if len(r) > 10:
            exp["x2"] = r[10]
    k.step(stick, fire, prev90, c8f)
    prev90 = c90
    if not old:
        got = dict(x0=k.xs[0], x1=k.xs[1], path=k.path, screen=k.screen, c1c=k.c1c, pose=k.pose, face=k.face, jump=k.jump)
        if "x2" in exp:
            got["x2"] = k.xs[2]
    else:
        got = dict(x=k.x, path=k.path, screen=k.screen, jump=k.jump, c1c=k.c1c & 0x1F, pose=k.pose, face=k.face)
    if got != exp:
        bad += 1
        if bad <= 12:
            print(f"frame {f}: " + " ".join(f"{n}:{got[n]:02X}!={exp[n]:02X}" for n in exp if got[n] != exp[n]))
print("mismatching frames:", bad, "of", len(rows))
sys.exit(1 if bad else 0)
