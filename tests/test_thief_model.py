#!/usr/bin/env python3
"""python -I tests/test_thief_model.py tests/golden/thief_idle.txt   (cols: 90,1B,1F,11,28,63,58,1A,14)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from kk_model import Thief  # noqa: E402

rows = [[int(x, 16) for x in l.split()[2:]] for l in Path(sys.argv[1]).read_text().splitlines()[1:]]
t = Thief(time=0x49)
bad = 0
for f, r in enumerate(rows):
    t.step(r[0], kop_path=0, kop_screen=0)
    t.tick_timer(r[0])
    got = [t.x, t.path, t.screen, t.time, t.anim]
    exp = [r[1], r[2], r[3], r[4], r[5]]
    if got != exp:
        bad += 1
        if bad <= 10:
            print(f"frame {f} $90={r[0]:02X}: got {[hex(x) for x in got]} exp {[hex(x) for x in exp]}")
print("mismatching frames:", bad, "of", len(rows))
sys.exit(1 if bad else 0)
