#!/usr/bin/env python3
"""Dynamic background scenery for the NES port: escalator steps (screens 0, 7) and elevator doors (screen 4).

The Atari draws both with player P2 over the playfield (docs/ATARI_RE_SPEC.md 9, code AC88-AD99):
  * Escalator: quad-width P2 staircase, one 4x4 px step per 4 rows, written to $0E80 (screen 0, floor 1,
    bits climbing right, HPOS $B8DA[$48]) or $0E60/$0EA0 (screen 7, floors 2 and 0, climbing left, HPOS
    $B8DE[$48]); $48 = $B8E2[($8F>>2)&3], first step $48+1 rows high. PRIOR = 4 on those floors, so P2
    (colour $0C) shows only on COLBK pixels (the dark band of the escalator art).
  * Elevator (screen 4): background id 6 = closed doors, 7 = open car; the car floor (S_AEDE) is open while
    $8E is $80..$EF, and in the transition frames ($70-$73, $F0-$F3) shows the open car plus P2 $C3
    (2 px door edges, colour $C0) at HPOS $78, 25 rows.

This tool rebuilds those pixels per phase/state from the cleaned composite (same crop/cleanup as
tools/gen_bg.py) and quantises them with the existing bg_data palettes; every new 8x8 tile is appended after
the screen's bg tiles (ids bg_ntiles[s]..).  The image is built in the 160 px Atari space (the phase
geometry is verified there) and then stretched to 256 px with gen_bg.py's mapping: 1.6x horizontal
(docs/DECISIONS_PENDING.md W1).  The elevator car column is 8 px at 160 and 12 px at 256, so it spans two
8 px tile columns.  The elevator needs teal, which no global palette holds: screen 4 never uses one of the
4 BG palettes, so that palette is redefined on screen 4 only (cell of the door column, 16 px wide = the
whole car).

Verification (always printed): synthesized escalator phases vs every Atari screenshot of screens 0/7
(assets/atari/runtime/screens/shots), elevator open/transition template vs shots 605/685.

Output (--emit): src/dyn_data.c (PRG bank 2) / src/dyn_data.h, preview assets/data/dyn_preview.png.
Re-run after every gen_bg.py --emit (build.ps1 checks the bg_data fingerprint).

Usage: python -I tools/gen_dyn.py [--emit]
"""
import argparse
import csv
import hashlib
import re
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SCR = ROOT / 'assets/atari/runtime/screens'
SW, TH = 256, 24            # NES playfield: 1.6x the 160 px Atari playfield (W1)
TW = SW // 8                # 32 tile columns
# BG tiles must stay below the HUD font (BG+OBJ pattern tables are separate on NES, so the old
# GBC-derived $80 cap does not apply; docs/NES_FULL_WIDTH_PLAN.md "CHR")
TILE_LIMIT = re.search(r'#define HUD_T0\s+(\w+)',
                       (ROOT / 'src/hud_data.h').read_text()).group(1)
TILE_LIMIT = int(TILE_LIMIT.rstrip('uU'), 0)

ap = argparse.ArgumentParser()
ap.add_argument('--emit', action='store_true')
args = ap.parse_args()

# ---------------------------------------------------------------- Atari constants (ROM tables)
B8DA = [0x6E, 0x6D, 0x6C, 0x6B]     # screen 0 floor 1 P2 HPOS by $48
B8DE = [0x72, 0x73, 0x74, 0x75]     # screen 7 floors 0/2 P2 HPOS by $48
B8E2 = [0x02, 0x01, 0x00, 0x03]     # $48 by ($8F>>2)&3
SKY = (106, 124, 244)
BLACK = (0, 0, 0)
DARK = (0, 18, 0)                   # COLBK of the escalator bands / Atari colour $C0 (door edges)
STRIPE = (205, 198, 210)            # escalator P2 colour $0C
TEAL = (0, 130, 103)                # open car interior
GREEN = (0, 95, 0)                  # wall; also COLBK inside the escalator band
CYAN = (127, 255, 246)              # car ceiling light
# open car colours in cells whose palette has no teal (top of the floor-2 car, bottom row of the floor-0
# car): one flat dark grey header like the closed door's top there, instead of olive / yellow pixels
PREFER = {TEAL: [0x1C, 0x2D], CYAN: [0x1C, 0x2D]}

# NES 2C02 RGB, same table as tools/gen_bg.py
NES = dict([
    (0x00, (84, 84, 84)), (0x01, (0, 30, 116)), (0x02, (8, 16, 144)), (0x03, (48, 0, 136)), (0x04, (68, 0, 100)),
    (0x05, (92, 0, 48)), (0x06, (84, 4, 0)), (0x07, (60, 24, 0)), (0x08, (32, 42, 0)), (0x09, (8, 58, 0)),
    (0x0A, (0, 64, 0)), (0x0B, (0, 60, 0)), (0x0C, (0, 50, 60)), (0x0F, (0, 0, 0)),
    (0x10, (152, 150, 152)), (0x11, (8, 76, 196)), (0x12, (48, 50, 236)), (0x13, (92, 30, 228)), (0x14, (136, 20, 176)),
    (0x15, (160, 20, 100)), (0x16, (152, 34, 32)), (0x17, (120, 60, 0)), (0x18, (84, 90, 0)), (0x19, (40, 114, 0)),
    (0x1A, (8, 124, 0)), (0x1B, (0, 118, 40)), (0x1C, (0, 102, 120)),
    (0x20, (236, 238, 236)), (0x21, (76, 154, 236)), (0x22, (120, 124, 236)), (0x23, (176, 98, 236)),
    (0x24, (228, 84, 236)), (0x25, (236, 88, 180)), (0x26, (236, 106, 100)), (0x27, (212, 136, 32)),
    (0x28, (160, 170, 0)), (0x29, (116, 196, 0)), (0x2A, (76, 208, 32)), (0x2B, (56, 204, 108)),
    (0x2C, (56, 180, 204)), (0x2D, (60, 60, 60)),
    (0x31, (168, 204, 236)), (0x32, (188, 188, 236)), (0x33, (212, 178, 236)), (0x34, (236, 174, 236)),
    (0x35, (236, 174, 212)), (0x36, (236, 180, 176)), (0x37, (228, 196, 144)), (0x38, (204, 210, 120)),
    (0x39, (180, 222, 120)), (0x3A, (168, 226, 144)), (0x3B, (152, 226, 180)), (0x3C, (160, 214, 228)),
    (0x3D, (160, 162, 160)),
])


def nes_of(c):
    return min(NES, key=lambda k: sum((a - b) ** 2 for a, b in zip(NES[k], c)))


# ---------------------------------------------------------------- bg_data (generated by gen_bg.py)
def c_arrays(path):
    txt = path.read_text()
    out = {}
    for m in re.finditer(r'const uint8_t (\w+)\[\] = \{([^}]*)\};', txt):
        out[m.group(1)] = [int(v) for v in m.group(2).replace('\n', ' ').split(',') if v.strip()]
    return out


BGF = [ROOT / 'src/bg_data.c', ROOT / 'src/bg_data_a.c', ROOT / 'src/bg_data_b.c']
BG = {}
for f in BGF:
    BG.update(c_arrays(f))
FINGERPRINT = hashlib.sha1(b''.join(f.read_bytes().replace(b'\r\n', b'\n') for f in BGF)).hexdigest()[:16]
bg_pal = BG['bg_pal']
bg_ntiles = BG['bg_ntiles']


def chr_tiles(s):
    raw = BG[f'bg_chr_{s}']
    tiles = []
    for t in range(len(raw) // 16):
        b = raw[t * 16:t * 16 + 16]
        tiles.append(np.array([[((b[2 * y] >> (7 - x)) & 1) | (((b[2 * y + 1] >> (7 - x)) & 1) << 1)
                                for x in range(8)] for y in range(8)], np.uint8))
    return tiles


def chr_bytes(t):
    out = []
    for y in range(8):
        out.append(sum(((int(t[y, x]) & 1) << (7 - x)) for x in range(8)))
        out.append(sum((((int(t[y, x]) >> 1) & 1) << (7 - x)) for x in range(8)))
    return out


# ---------------------------------------------------------------- Atari images (gen_bg.py crop + clean)
def pf_of(path):
    return np.asarray(Image.open(path).convert('RGB').crop((8, 23, 328, 204)).resize((160, 181), Image.NEAREST))


def scale_x(a):
    """160 px Atari space -> 256 px NES playfield: source column floor(dst*160/256) = dst*5/8, the
    renderer's screen_x = world_x*8/5 inverted (gen_bg.py --width 256 uses the same index)."""
    return a[:, (np.arange(SW) * a.shape[1]) // SW]


def composite(s):
    a = pf_of(SCR / f'screen_{s}.png').copy()
    if s == 4:                                  # gen_bg.py ELEV: floor-0 open car -> closed door of floor 3
        a[121:145, 72:80] = a[57:81, 72:80]
    a[0:18] = SKY
    a[173:181] = BLACK
    for y in range(160, 173):
        for x in range(1, 160):
            if tuple(a[y, x]) == (148, 161, 255):
                a[y, x] = a[y, x - 1]
    out = np.zeros((192, 160, 3), np.uint8)
    out[:181] = a
    return out


def composite_s(s):
    """the composite in NES playfield space (256 px)."""
    return scale_x(composite(s))


def eq(a, c):
    return (a == np.array(c, np.uint8)).all(-1)


# ---------------------------------------------------------------- escalator P2 patterns (AC88-ACFB)
def p2_rows(s, j):
    rows, x = [], j
    a = 2 if s == 0 else 0x40
    for _ in range(25):
        rows.append(a)
        x -= 1
        if x < 0:
            x = 3
            a = ((a << 1) & 0xFF) if s == 0 else (a >> 1)
    return rows


ESC = {0: [89], 7: [57, 121]}           # first playfield line of each P2 band (PMG row R -> y = R - 39)


def colbk_mask(s):
    """COLBK pixels of the P2 bands: the playfield's own dark pixels hide P2 too (same colour as COLBK),
    so the mask is the union of the P2 pixels seen in all Atari shots of the screen (4 phases)."""
    m = np.zeros((192, 160), bool)
    for _, a in shots(s):
        for y0 in ESC[s]:
            m[y0:y0 + 25, 40:110] |= eq(a[y0:y0 + 25, 40:110], STRIPE)
    return m


def esc_phase(s, base, k, colbk):
    """Atari pixels of screen s at escalator phase k = ($8F>>2)&3."""
    j = B8E2[k]
    h = (B8DA if s == 0 else B8DE)[j] - 0x30
    img = base.copy()
    for y0 in ESC[s]:
        for yy, v in enumerate(p2_rows(s, j)):
            for b in range(8):
                if v & (0x80 >> b):
                    for x in range(h + 4 * b, h + 4 * b + 4):
                        if 0 <= x < 160 and colbk[y0 + yy, x]:
                            img[y0 + yy, x] = STRIPE
    return img


def esc_clean(a, colbk):
    """COLBK (= the wall green) where P2 can show: the mode composite has a stripe/dark/green mix there."""
    a = a.copy()
    a[colbk[:a.shape[0]]] = GREEN
    return a


# ---------------------------------------------------------------- quantisation helpers
class Screen:
    def __init__(self, s):
        self.s = s
        self.tiles = chr_tiles(s)
        self.map = np.array(BG[f'bg_map_{s}'], int).reshape(TH, TW)
        self.attr = np.array(BG[f'bg_attr_{s}'], int).reshape(TH // 2, TW // 2)
        self.q = np.zeros((192, SW), np.uint8)
        for ty in range(TH):
            for tx in range(TW):
                self.q[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8] = self.tiles[self.map[ty, tx]]
        self.atari = composite_s(s)
        # learned Atari colour -> palette index per palette (majority over the screen)
        votes = {}
        for y in range(192):
            for x in range(SW):
                k = (int(self.attr[y // 16, x // 16]), tuple(int(v) for v in self.atari[y, x]))
                votes.setdefault(k, {}).setdefault(int(self.q[y, x]), 0)
                votes[k][int(self.q[y, x])] += 1
        self.learned = {k: max(v, key=v.get) for k, v in votes.items()}
        self.new = []                          # appended tiles (index arrays)
        self.pal_over = {}                     # (cx, cy) -> palette id override
        self.extra_pal = None                  # (palette id, 4 NES colours)

    def pal_colours(self, p):
        if self.extra_pal and p == self.extra_pal[0]:
            return self.extra_pal[1]
        return bg_pal[p * 4:p * 4 + 4]

    def cell_pal(self, cx, cy):
        return self.pal_over.get((cx, cy), int(self.attr[cy, cx]))

    def index_of(self, p, rgb, learned_ok=True):
        rgb = tuple(int(v) for v in rgb)
        if learned_ok and (p, rgb) in self.learned:
            return self.learned[(p, rgb)]
        cols = self.pal_colours(p)
        for want in PREFER.get(rgb, []):
            if want in cols:
                return cols.index(want)
        return min(range(4), key=lambda i: sum((a - b) ** 2 for a, b in zip(NES[cols[i]], rgb)))

    def quant_tile(self, img, tx, ty, fallback=None):
        """index tile at (tx,ty) of Atari image img; unchanged pixels keep the bg_data indices.  A colour the
        cell's palette never showed in bg_data takes the fallback image's pixel instead (a P2 stripe pixel in a
        cell without white stays wall green rather than turning olive)."""
        p = self.cell_pal(tx // 2, ty // 2)
        override = (tx // 2, ty // 2) in self.pal_over
        out = np.zeros((8, 8), np.uint8)
        for y in range(8):
            for x in range(8):
                X, Y = tx * 8 + x, ty * 8 + y
                c = img[Y, X]
                if not override and (c == self.atari[Y, X]).all():
                    out[y, x] = self.q[Y, X]
                    continue
                if (not override and fallback is not None
                        and (p, tuple(int(v) for v in c)) not in self.learned):
                    c = fallback[Y, X]
                out[y, x] = self.index_of(p, c, learned_ok=not override)
        return out

    def tile_id(self, t):
        for i, e in enumerate(self.tiles):
            if (e == t).all():
                return i
        for i, e in enumerate(self.new):
            if (e == t).all():
                return bg_ntiles[self.s] + i
        self.new.append(t)
        return bg_ntiles[self.s] + len(self.new) - 1

    def render(self, ids, pal_of):
        pix = np.zeros((192, SW, 3), np.uint8)
        for ty in range(TH):
            for tx in range(TW):
                i = ids[ty][tx]
                t = self.tiles[i] if i < bg_ntiles[self.s] else self.new[i - bg_ntiles[self.s]]
                cols = self.pal_colours(pal_of(tx // 2, ty // 2))
                pix[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8] = np.array([NES[c] for c in cols], np.uint8)[t]
        return pix


def shots(screen):
    rows = list(csv.DictReader(open(SCR / 'shots.csv')))
    return [(int(r['frame']), pf_of(SCR / f"shots/{int(r['frame']):04d}.png")) for r in rows if r['screen'] == str(screen)]


previews = []

# ---------------------------------------------------------------- escalators
esc_out = {}
for s in (0, 7):
    sc = Screen(s)
    colbk = colbk_mask(s)
    base = esc_clean(composite(s)[:181], colbk)     # Atari 160 px space: the phase geometry is verified there
    ph160 = [esc_phase(s, base, k, colbk) for k in range(4)]
    ph = [scale_x(a) for a in ph160]
    # verify against the Atari shots: each shot's P2 bands must equal one phase (ignoring sprite pixels)
    hits, near, tot = [0] * 4, 0, 0
    for f, a in shots(s):
        for y0 in ESC[s]:
            tot += 1
            reg = slice(y0, y0 + 25), slice(40, 110)
            best = min(range(4), key=lambda k: int((a[reg] != ph160[k][reg]).any(-1).sum()))
            d = int((a[reg] != ph160[best][reg]).any(-1).sum())
            if d == 0:
                hits[best] += 1
            elif d < 30:
                near += 1                       # Kop / thief / obstacle over the band
    print(f'screen {s}: escalator bands exact per phase {hits}, sprite-covered {near}, of {tot}')
    # mode of the 4 phases vs the composite (the composite is a mode over many frames)
    full = [np.zeros((192, SW, 3), np.uint8) for _ in range(4)]
    for k in range(4):
        full[k][:181] = ph[k]
        full[k][181:] = sc.atari[181:]
    # tiles that change between phases
    fb = sc.atari
    qk = [[[sc.quant_tile(full[k], tx, ty, fb) for tx in range(TW)] for ty in range(TH)] for k in range(4)]
    dyn = [(tx, ty) for ty in range(TH) for tx in range(TW)
           if any(not (qk[k][ty][tx] == qk[0][ty][tx]).all() for k in range(1, 4))
           or not (qk[0][ty][tx] == sc.tiles[sc.map[ty, tx]]).all()]
    ids = {(tx, ty): [sc.tile_id(qk[k][ty][tx]) for k in range(4)] for (tx, ty) in dyn}
    runs = []
    for (tx, ty) in dyn:
        if runs and runs[-1][1] == ty and runs[-1][0] + runs[-1][2] == tx:
            runs[-1][2] += 1
        else:
            runs.append([tx, ty, 1])
    print(f'screen {s}: {len(dyn)} dynamic positions in {len(runs)} runs, {len(sc.new)} new tiles, '
          f'total {bg_ntiles[s] + len(sc.new)} / {TILE_LIMIT}')
    assert bg_ntiles[s] + len(sc.new) <= TILE_LIMIT, f'screen {s}: too many BG tiles'
    esc_out[s] = (sc, runs, ids)
    for k in range(4):
        m = [[ids.get((tx, ty), [sc.map[ty, tx]] * 4)[k] for tx in range(TW)] for ty in range(TH)]
        previews.append((f's{s} ph{k}', full[k], sc.render(m, lambda cx, cy: int(sc.attr[cy, cx]))))

# ---------------------------------------------------------------- elevator (screen 4)
sc = Screen(4)
used = set(int(v) for v in sc.attr.ravel())
free = [p for p in range(4) if p not in used]
CAR_X = 72                                  # Atari car column x 72..79 (P2 HPOS $78)
CAR_TX = (CAR_X * SW) // 160 // 8           # NES tile column of the scaled car: x 116..127 = columns 14+15
CAR_TC = 2                                  # the 8 px car is 12 px at 1.6x: two tile columns (W1 gotcha)
CAR_Y0 = [121, 89, 57]                      # first car line per floor (PMG rows $A0/$80/$60)
# open car template: Atari shot 605 (floor 0 car open, nobody in front)
open_t = pf_of(SCR / 'shots/0605.png')[121:146, CAR_X:CAR_X + 8].copy()
part_t = open_t.copy()
part_t[:, [0, 1, 6, 7]] = DARK              # P2 $C3, colour $C0, 25 rows
chk = pf_of(SCR / 'shots/0685.png')[121:146, CAR_X:CAR_X + 8]
kopc = {(0, 0, 0), (24, 26, 167), (200, 160, 50)}
mask = np.array([[tuple(int(v) for v in chk[y, x]) not in kopc for x in range(8)] for y in range(25)])
print('elevator: transition template vs shot 685 (non-Kop px): %d/%d equal' %
      (int(((chk == part_t).all(-1) & mask).sum()), int(mask.sum())))
print('elevator: shot 685 colours', sorted({tuple(int(v) for v in p) for p in chk.reshape(-1, 3)}))
door_p = int(sc.attr[6, CAR_TX // 2])       # palette gen_bg.py chose for the door column (mid floor 1)


def learned_nes(rgb):
    return bg_pal[door_p * 4 + sc.learned[(door_p, rgb)]]


if free:
    ep = free[0]
    colours = [bg_pal[0], learned_nes(DARK), learned_nes((0, 95, 0)), nes_of(TEAL)]
    sc.extra_pal = (ep, colours)
    for cy in range(4, 9):                  # door column cells, rows 64..143 (cy 3 keeps palette 0: skyline grey)
        sc.pal_over[(CAR_TX // 2, cy)] = ep
    print('elevator: palette', ep, 'redefined on screen 4 as', [hex(c) for c in colours])
else:
    ep = 0xFF
    print('elevator: no free palette on screen 4, door column quantised with the existing palettes')


def car_img(f, state):
    """screen 4 in Atari space (160 px) with floor f's car drawn in the given state."""
    a = composite(4)
    y0 = CAR_Y0[f]
    if state:
        a[y0:y0 + 24, CAR_X:CAR_X + 8] = open_t[:24]
        if state == 1:
            a[y0:y0 + 25, CAR_X:CAR_X + 2] = DARK
            a[y0:y0 + 25, CAR_X + 6:CAR_X + 8] = DARK
    return a


# static overrides: every tile of the re-paletted cells, closed doors
fix = []
closed = sc.atari
for (cx, cy) in sorted(sc.pal_over):
    for ty in (2 * cy, 2 * cy + 1):
        for tx in (2 * cx, 2 * cx + 1):
            t = sc.quant_tile(closed, tx, ty)
            i = sc.tile_id(t)
            if i != sc.map[ty, tx]:
                fix.append((tx, ty, i))
fixmap = {(tx, ty): i for tx, ty, i in fix}
elev = []
for f in range(3):
    ty0 = CAR_Y0[f] // 8
    st = []
    for state in range(3):              # 0 closed, 1 transition, 2 open
        img = scale_x(car_img(f, state))
        st.append([sc.tile_id(sc.quant_tile(img, CAR_TX + c, ty))
                   for ty in range(ty0, ty0 + 4) for c in range(CAR_TC)])
    elev.append((ty0, st))
print(f'elevator: {len(fix)} static overrides, rows per floor {[e[0] for e in elev]}, '
      f'{len(sc.new)} new tiles, total {bg_ntiles[4] + len(sc.new)}')
assert bg_ntiles[4] + len(sc.new) <= TILE_LIMIT
for f in range(3):
    for state in range(3):
        if f != 0 and state != 2:
            continue
        m = [[fixmap.get((tx, ty), int(sc.map[ty, tx])) for tx in range(TW)] for ty in range(TH)]
        ty0, st = elev[f]
        for i in range(4):
            for c in range(CAR_TC):
                m[ty0 + i][CAR_TX + c] = st[state][2 * i + c]
        previews.append((f's4 f{f} st{state}', scale_x(car_img(f, state)), sc.render(m, sc.cell_pal)))

# ---------------------------------------------------------------- preview
W = SW * 2 + 8
pv = Image.new('RGB', (W * 4, 200 * ((len(previews) + 3) // 4)), (40, 40, 40))
for i, (name, a, n) in enumerate(previews):
    x, y = (i % 4) * W, (i // 4) * 200
    pv.paste(Image.fromarray(a), (x, y))
    pv.paste(Image.fromarray(n), (x + 164, y))
pv.save(ROOT / 'assets/data/dyn_preview.png')
print('wrote assets/data/dyn_preview.png (Atari | NES per state)')

# ---------------------------------------------------------------- emit
if args.emit:
    def arr(name, vals, per=16, static=False):
        out = [f'const uint8_t {name}[] = {{']
        for i in range(0, len(vals), per):
            out.append('  ' + ','.join(str(v) for v in vals[i:i + per]) + ',')
        return out + ['};']

    c = ['#include "dyn_data.h"', '/* generated by tools/gen_dyn.py - do not edit */']
    h = ['#ifndef DYN_DATA_H', '#define DYN_DATA_H', '#include <stdint.h>',
         '/* generated by tools/gen_dyn.py - do not edit (re-run after gen_bg.py --emit) */',
         f'#define DYN_BG_FINGERPRINT "{FINGERPRINT}"  /* sha1 of src/bg_data*.c used (build.ps1 checks it) */',
         '#define DYN_BANK 2u            /* PRG bank of dyn_data.c (build.ps1 -Wf-bo2) */']
    for s, scr in ((0, esc_out[0][0]), (4, sc), (7, esc_out[7][0])):
        c += arr(f'dyn_chr_{s}', [b for t in scr.new for b in chr_bytes(t)] or [0])
        h.append(f'#define DYN_T0_{s} {bg_ntiles[s]}u   /* first appended tile id (= bg_ntiles[{s}]) */')
        h.append(f'#define DYN_N_{s} {len(scr.new)}u')
        h.append(f'extern const uint8_t dyn_chr_{s}[];')
    # escalator runs: n, then per run x, y, w, ids[phase 0..3][w]  (BG map coordinates, playfield-relative)
    h.append('/* escalator step tiles: count, then per run tx, ty, w, w ids for phase 0, 1, 2, 3 (phase = ($8F>>2)&3) */')
    for s in (0, 7):
        scr, runs, ids = esc_out[s]
        v = [len(runs)]
        for tx, ty, w in runs:
            v += [tx, ty, w]
            for k in range(4):
                v += [ids[(tx + i, ty)][k] for i in range(w)]
        c += arr(f'dyn_esc_{s}', v)
        h.append(f'extern const uint8_t dyn_esc_{s}[];')
    h.append('/* elevator (screen 4): static tile overrides (count, then tx, ty, id), palette, door cells */')
    c += arr('dyn_s4_fix', [len(fix)] + [v for t in fix for v in t])
    h.append('extern const uint8_t dyn_s4_fix[];')
    h.append(f'#define DYN_ELEV_PAL {ep}u    /* BG palette redefined on screen 4 (0xFF = none) */')
    c += arr('dyn_elev_pal', sc.extra_pal[1] if sc.extra_pal else [0, 0, 0, 0])
    h.append('extern const uint8_t dyn_elev_pal[4];')
    cells = sorted(sc.pal_over)
    c += arr('dyn_elev_cells', [len(cells)] + [v for cc in cells for v in cc])
    h.append('extern const uint8_t dyn_elev_cells[];   /* count, then (cx, cy) 16x16 cells using DYN_ELEV_PAL */')
    h.append(f'#define DYN_ELEV_TX {CAR_TX}u   /* first car tile column */')
    h.append(f'#define DYN_ELEV_W {CAR_TC}u    /* car tile columns (8 px at 160 -> 12 px at 256) */')
    h.append('extern const uint8_t dyn_elev_ty[3];      /* first car tile row per floor */')
    c += arr('dyn_elev_ty', [e[0] for e in elev])
    h.append('extern const uint8_t dyn_elev[72];        /* [floor][state 0 closed,1 moving doors,2 open][4 rows][2 cols] */')
    c += arr('dyn_elev', [i for e in elev for st in e[1] for i in st], 8)
    h.append('#endif')
    (ROOT / 'src/dyn_data.h').write_text('\n'.join(h) + '\n')
    (ROOT / 'src/dyn_data.c').write_text('\n'.join(c) + '\n')
    print('wrote src/dyn_data.c/.h, fingerprint', FINGERPRINT)
