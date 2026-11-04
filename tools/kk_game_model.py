#!/usr/bin/env python3
"""Game-rule model of Keystone Kapers (Atari): collisions, hit / death / pickup / catch, sound-effect
countdown ($17/$12), timer drain, score + extra life, bonus count, lives, level restart, game over.

Reference for src/engine.c (engine step 2).  Read from the disassembly (docs/atari_disasm.txt):
  A436-A46B bonus count, A4F3-A557 hit/death gating + timer, A76C-A841 collision resolution,
  A877-A8E9 effect countdown and its end actions, A49A level restart, S_AF10 score, S_AFC2 spawn.
Kop movement is tools/kk_model.py, obstacle motion tools/obstacle_model.py.

Hardware collisions (GTIA, pixel exact) are replaced by bounding boxes of the opaque pixels of each
shape (assets/data/sprites.json, computed by frame_boxes()).  Latency: the state at the end of frame
N is displayed during frame N+1, latched in $0D+f and read by the logic of that same frame N+1.

    python tools/kk_game_model.py            # check against tests/golden/ball1.txt (ball hit)
    python tools/kk_game_model.py --boxes    # print the box table used by src/engine.c
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import obstacle_model as om  # noqa: E402

# frame index = src/spr_data.h SPR_F_* ; type -> frame = spr_obj_type
KOP_POSE_FRAME = [5, 0, 1, 2, 3, 4, 5, 6]
OBJ_TYPE_FRAME = [None, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, None, None, None, 18, 19]
B5F7 = (0x02, 0x05, 0x04, 0x10)          # pickup score per floor (hundreds, BCD)
BEF2 = (0xA0, 0x80, 0x60)                # radio copy test X
BEF8 = (0x06, 0x05, 0x03)                # radio mask keep bits
BEE1 = (0x00, 0x00, 0x00, 0x07, 0x00, 0x04, 0x07, 0x06)   # $34 after a radio hit, by mask
BEE9 = (0x00, 0x98, 0x78, 0x78, 0x58, 0x58, 0x58, 0x58)   # $30 after a radio hit, by mask


def frame_boxes():
    """(top, bottom, col0, col1) per sprite frame: rows relative to the pivot (y down), opaque columns."""
    d = json.loads((ROOT / 'assets/data/sprites.json').read_text())
    out = []
    for f in d['frames']:
        rows, p = f['rows_bottom_first'], f['pivot_row']
        nz = [r for r, (b, _) in enumerate(rows) if b]
        m = 0
        for b, _ in rows:
            m |= b
        cols = [c for c in range(8) if m & (0x80 >> c)]
        out.append((p - max(nz), p - min(nz), cols[0], cols[-1], f['name']))
    return out


BOXES = frame_boxes()


def box(frame, x, y0, flip):
    """x = HPOS, y0 = pivot line; returns (l, r, t, b) inclusive."""
    t, b, c0, c1, _ = BOXES[frame]
    if flip:
        c0, c1 = 7 - c1, 7 - c0
    return x + c0, x + c1, y0 + t, y0 + b


def overlap(a, b):
    return max(a[0], b[0]) <= min(a[1], b[1]) and max(a[2], b[2]) <= min(a[3], b[3])


def copies(x, fl):
    """HPOS of every drawn copy of an object (DLI B2C3-B30F, spec 9)."""
    m = fl & 7
    if m == 4:
        x2 = (x + 0x40) & 0xFF
        if x >= 0xA0:
            x2 = (x - (0x7A if fl & 8 else 0x81)) & 0xFF
        return [x, x2]
    if m == 6:
        return [x, (x + 0x20) & 0xFF, (x + 0x40) & 0xFF]
    if m == 7:
        return [x, (x + 0x20) & 0xFF]
    return [x]


def kop_touches(kop_pose, kop_face, kop_x, height, t, ox, ofl, oh):
    """Kop (P3) against the object slot of his floor: True = the GTIA would latch $0D+f."""
    fr = OBJ_TYPE_FRAME[t] if t < len(OBJ_TYPE_FRAME) else None
    if t == 0 or fr is None:
        return False
    k = box(KOP_POSE_FRAME[kop_pose], kop_x, -height, kop_face & 8)
    for cx in copies(ox, ofl):
        if overlap(k, box(fr, cx, oh - 0x1A, ofl & 8)):
            return True
    return False


def bcd_add(a, b, c=0):
    lo = (a & 0x0F) + (b & 0x0F) + c
    hi = (a >> 4) + (b >> 4)
    if lo > 9:
        lo -= 10
        hi += 1
    c = 0
    if hi > 9:
        hi -= 10
        c = 1
    return (hi << 4) | lo, c


class Rules:
    """Score / lives / effect state.  Field names = Atari zero page."""

    def __init__(self):
        self.s25 = self.s26 = 0   # score BCD (hundreds)
        self.l21 = 3              # spare lives
        self.l17 = self.l12 = 0   # effect id / step
        self.l6E = 0              # slot type restored after a hit (radio) else 0
        self.over = False

    def score(self, a):           # S_AF10
        old = self.s25
        self.s26, c = bcd_add(self.s26, a)
        self.s25, c = bcd_add(self.s25, 0, c)
        if c:
            self.s25 = self.s26 = 0xAA
            self.over = True
        if old != self.s25 and self.l21 + 1 < 4:
            self.l21 += 1

    def effect_tick(self, c90):
        """A877-A8E9 with $90 before the increment.  Returns 'end4', 'end5', 'end6' or None."""
        if not self.l17:
            return None
        if self.l17 >= 4 and c90 & 3:
            return None
        self.l12 -= 1
        if self.l12 >= 0:
            return None
        ident, self.l17 = self.l17, 0
        return f'end{ident}' if ident >= 4 else None


def check_ball1(verbose=True):
    """tests/golden/ball1.txt: Kop stands at $CF (screen 1, floor 0, facing left, pose 6) while the ball
    rolls into him.  Predicts $0D (latched collision), the hit start ($6C=5) and the slot clear."""
    lines = (ROOT / 'tests/golden/ball1.txt').read_text().splitlines()
    hdr = [int(v, 16) for v in lines[0].split()[2:]]
    rows = [dict(zip(hdr, [int(v, 16) for v in ln.split()[2:]])) for ln in lines[1:]]
    pose = []                       # Kop pose per row: walking left until the wrap, then standing
    for ln in lines[1:]:
        pose.append(6 if ln.split()[1] == 'centre' else None)
    rules = Rules()
    latch = False
    first_latch = hit_row = clear_row = None
    for i, r in enumerate(rows):
        c90 = (r[0x90] - 1) & 0xFF
        if latch and first_latch is None:
            first_latch = i
        if latch and rules.l17 == 0 and hit_row is None:          # A76C..A82B: ball = hit
            rules.l17, rules.l12 = 5, 8
            hit_row = i
        end = rules.effect_tick(c90)
        if end == 'end5' and clear_row is None:
            clear_row = i                                          # A8C1: slot = $6E (0)
        if pose[i] == 6:
            touch = kop_touches(6, 8, r[0x2C], 0, r[0x75], r[0x30], r[0x34], r[0x71])
        else:
            touch = False
        latch = touch                  # displayed during the next frame, latched and read by it
    exp_latch = next(i for i, r in enumerate(rows) if r[0x0D])
    # $6C is the copy of $17 taken at the start of a frame (A501): the hit began one row earlier
    exp_hit = next(i for i, r in enumerate(rows) if r[0x6C] == 5) - 1
    exp_clear = next(i for i, r in enumerate(rows) if i > exp_hit and r[0x75] == 0)
    res = [('latch $0D', first_latch, exp_latch), ('hit $6C=5', hit_row, exp_hit), ('slot clear', clear_row, exp_clear)]
    bad = 0
    for name, got, exp in res:
        ok = got == exp
        bad += not ok
        if verbose:
            print(f'{name:10s} model row {got}  atari row {exp}  {"ok" if ok else "MISMATCH"}')
    return bad


def main():
    if '--boxes' in sys.argv:
        for i, (t, b, c0, c1, n) in enumerate(BOXES):
            print(f'    {{ {t:4d}, {b:3d}, {c0}, {c1} }},   /* {i:2d} {n} */')
        return 0
    bad = check_ball1()
    print('ball1: ' + ('model matches' if not bad else f'{bad} mismatches'))
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
