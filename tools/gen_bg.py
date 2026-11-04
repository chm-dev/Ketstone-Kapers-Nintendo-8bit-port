#!/usr/bin/env python3
"""Background art for the NES port: 8 screen composites -> shared 4x(3+1) palette set + tilemaps.

Input : assets/atari/runtime/screens/screen_0..7.png (336x224, 2 px per colour clock).
        Playfield crop = columns 4..163 (clocks), lines 23..203 (181 lines), padded to 192 = 24 tile rows.
Method: the Atari colours (about 25, DLI colour bands) cannot fit one NES palette per 16x16 cell, so
        a global search picks BG colour + 4 triples that minimise the colour error over all cells of
        all screens; each 16x16 attribute cell then takes its best palette and its pixels snap to it.
Output: assets/data/bg_preview_N.png (quantised result), console stats (error, unique tiles per screen).
        --emit writes src/bg_data.c/.h (palette, per-screen CHR + 20x24 map + 10x12 attribute cells).

Usage: python tools/gen_bg.py [--emit] [--seed N]
"""
import argparse
import random
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SCR = ROOT / 'assets/atari/runtime/screens'
TW, TH = 20, 24

ap = argparse.ArgumentParser()
ap.add_argument('--emit', action='store_true')
ap.add_argument('--seed', type=int, default=1)
ap.add_argument('--restarts', type=int, default=12)
args = ap.parse_args()


SKY = (106, 124, 244)
# Cleanup of baked-in dynamic content (G9). Coordinates are in the 160x181 playfield crop.
#   (screen, x0, x1, y0, y1, refx): rows y0..y1-1, columns x0..x1-1 are overwritten with the pixel of
#   the same row at column refx (bands are horizontally uniform there).
COPYCOLS = [
    (1, 70, 82, 41, 52, 60),     # screen 1: money bag on the roof (x 72-80, y 41-51, over skyline/roof edge)
    (2, 70, 82, 74, 84, 64),     # screen 2: item on floor 3 (x 72-80, y 74-83)
    (2, 70, 82, 105, 116, 64),   # screen 2: item on floor 2 (y 105-115)
    (2, 70, 82, 138, 148, 64),   # screen 2: item on floor 1 (y 138-147)
]
# screen 4 elevator: the open car (floor 1, y 121-144) is replaced by the closed door of floor 3 (y 57-80)
ELEV = (4, 72, 80, 57, 121, 24)   # (screen, x0, x1, src_y0, dst_y0, nrows)
BLACK = (0, 0, 0)


def clean(s, a):
    a = a.copy()
    for (cs, x0, x1, y0, y1, rx) in COPYCOLS:
        if cs == s:
            for y in range(y0, y1):
                a[y, x0:x1] = a[y, rx]
    if s == ELEV[0]:
        _, x0, x1, sy, dy, n = ELEV
        a[dy:dy + n, x0:x1] = a[sy:sy + n, x0:x1]
    a[0:18] = SKY                       # Atari HUD line (score, hats, time, note) baked into sky rows 1-17
    a[173:181] = BLACK                  # Activision logo band below the street (Atari-only; NES HUD is separate)
    for y in range(160, 173):           # 1x2 px minimap-ish speck (148,161,255) on the entrance steps, x=75
        for x in range(1, 160):
            if tuple(a[y, x]) == (148, 161, 255):
                a[y, x] = a[y, x - 1]
    return a


def load(s):
    im = Image.open(SCR / f'screen_{s}.png').convert('RGB').crop((8, 23, 328, 204)).resize((160, 181), Image.NEAREST)
    im = Image.fromarray(clean(s, np.asarray(im)))
    out = Image.new('RGB', (160, 192))
    out.paste(im)
    return np.asarray(out)


shots = [load(s) for s in range(8)]
colors = sorted({tuple(int(v) for v in p) for a in shots for p in a.reshape(-1, 3)})
cidx = {c: i for i, c in enumerate(colors)}
NC = len(colors)
rgb = np.array(colors, float)
# weighted RGB distance (green-heavy, like the eye); black stays far from everything
D = np.sqrt((((rgb[:, None, :] - rgb[None, :, :]) * [0.3, 0.59, 0.11]) ** 2).sum(-1))
idx = [np.array([[cidx[tuple(p)] for p in row] for row in a]) for a in shots]

# histogram per 16x16 cell: (screen, cy, cx) -> counts[NC]
cells = np.zeros((8, 12, 10, NC))
for s in range(8):
    for cy in range(12):
        for cx in range(10):
            blk = idx[s][cy * 16:cy * 16 + 16, cx * 16:cx * 16 + 16]
            cells[s, cy, cx] = np.bincount(blk.ravel(), minlength=NC)
cells = cells.reshape(-1, NC)


def cost_pal(pal):
    """per-cell cost with palette = list of colour indices (incl. bg)."""
    m = D[:, pal].min(1)          # best distance from each colour to the palette
    return cells @ m


def total(bg, tri):
    c = np.stack([cost_pal([bg] + list(t)) for t in tri])   # (4, cells)
    return c.min(0).sum()


rng = random.Random(args.seed)
best = None
for restart in range(args.restarts):
    bg = rng.randrange(NC)
    tri = [[rng.randrange(NC) for _ in range(3)] for _ in range(4)]
    cur = total(bg, tri)
    improved = True
    while improved:
        improved = False
        for slot in range(-1, 12):          # -1 = bg
            for c in range(NC):
                if slot < 0:
                    nb, nt = c, tri
                else:
                    nb = bg
                    nt = [list(t) for t in tri]
                    nt[slot // 3][slot % 3] = c
                v = total(nb, nt)
                if v < cur - 1e-9:
                    cur, bg, tri, improved = v, nb, nt, True
    if best is None or cur < best[0]:
        best = (cur, bg, [list(t) for t in tri])
cur, bg, tri = best
pals = [[bg] + t for t in tri]
print('palette error', round(cur, 1), 'bg', colors[bg])
for p in pals:
    print('  ', [colors[i] for i in p])

# quantise: per cell choose palette, snap pixels
allc = np.stack([cost_pal(p) for p in pals])
choice = allc.argmin(0).reshape(8, 12, 10)
ntile = []
screens = []
for s in range(8):
    # tile 0 = solid colour 3 (black in palette 1): the margin around the 160 px pillarbox
    blank = np.full((8, 8), 3, int)
    tiles, tindex, nt = [blank], {blank.tobytes(): 0}, []
    q = np.zeros((192, 160), int)
    pix = np.zeros((192, 160, 3), np.uint8)
    for cy in range(12):
        for cx in range(10):
            p = pals[choice[s, cy, cx]]
            blk = idx[s][cy * 16:cy * 16 + 16, cx * 16:cx * 16 + 16]
            sub = D[blk][:, :, p].argmin(-1)
            q[cy * 16:cy * 16 + 16, cx * 16:cx * 16 + 16] = sub
            pix[cy * 16:cy * 16 + 16, cx * 16:cx * 16 + 16] = np.array(colors, np.uint8)[np.array(p)[sub]]
    for ty in range(TH):
        for tx in range(TW):
            t = q[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8]
            key = t.tobytes()
            if key not in tindex:
                tindex[key] = len(tiles)
                tiles.append(t)
            nt.append(tindex[key])
    ntile.append(len(tiles))
    screens.append((tiles, nt, choice[s]))
    Image.fromarray(pix).resize((320, 384), Image.NEAREST).save(ROOT / f'assets/data/bg_preview_{s}.png')
print('unique tiles per screen', ntile)

NES = [  # 2C02 RGB (FCEUX-like) for the usable colours
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
]
W3 = np.array([1.0, 1.0, 1.0])   # plain RGB: the eye-weighted one mapped green to teal


def nes_of(c):
    return min(NES, key=lambda e: (((np.array(e[1]) - np.array(c)) * W3) ** 2).sum())[0]


if args.emit:
    def chr_bytes(t):
        lo = [sum(((int(t[y, x]) & 1) << (7 - x)) for x in range(8)) for y in range(8)]
        hi = [sum((((int(t[y, x]) >> 1) & 1) << (7 - x)) for x in range(8)) for y in range(8)]
        # GBDK set_bkg_data takes Game Boy layout (lo,hi interleaved per row) on NES too
        return [b for pair in zip(lo, hi) for b in pair]

    def arr(name, vals, per=16):
        out = [f'const uint8_t {name}[] = {{']
        for i in range(0, len(vals), per):
            out.append('  ' + ','.join(str(v) for v in vals[i:i + per]) + ',')
        return out + ['};']

    pal_nes = []
    for p in pals:
        pal_nes += [nes_of(colors[i]) for i in p]
    pal_nes[0::4] = [pal_nes[0]] * 4          # one shared backdrop entry
    print('NES palettes', [hex(v) for v in pal_nes])
    h = ['#ifndef BG_DATA_H', '#define BG_DATA_H', '#include <stdint.h>',
         '/* generated by tools/gen_bg.py - do not edit */',
         f'#define BG_W {TW}u', f'#define BG_H {TH}u', '#define BG_SCREENS 8u',
         'extern const uint8_t bg_pal[16];            /* 4 palettes x (bg,c1,c2,c3), NES colour ids */',
         'extern const uint8_t bg_ntiles[BG_SCREENS]; /* tiles in bg_chr[s] */',
         'extern const uint8_t *const bg_chr[BG_SCREENS];  /* 16 bytes per tile, CHR-RAM format */',
         'extern const uint8_t *const bg_map[BG_SCREENS];  /* BG_W*BG_H tile ids */',
         'extern const uint8_t *const bg_attr[BG_SCREENS]; /* palette id per 16x16 cell, 10x12 */', '#endif']
    hdr = ['#include "bg_data.h"', '/* generated by tools/gen_bg.py - do not edit */']
    c = list(hdr)
    c += arr('bg_pal', pal_nes)
    c += arr('bg_ntiles', ntile)
    # screens 0-3 live in PRG bank 1 (bg_data_a.c), 4-7 in bank 2 (bg_data_b.c): build.ps1 adds -Wf-bo<N>
    banks = [list(hdr), list(hdr)]
    for s, (tiles, nt, ch) in enumerate(screens):
        chrb = [b for t in tiles for b in chr_bytes(t)]
        attr = [int(v) for v in ch.ravel()]     # one palette id per 16x16 cell, 10 per row
        banks[s >> 2] += arr(f'bg_chr_{s}', chrb) + arr(f'bg_map_{s}', nt, TW) + arr(f'bg_attr_{s}', attr, 10)
        h.insert(-1, f'extern const uint8_t bg_chr_{s}[], bg_map_{s}[], bg_attr_{s}[];')
    for n in ('chr', 'map', 'attr'):
        c.append(f'const uint8_t *const bg_{n}[BG_SCREENS] = {{' + ','.join(f'bg_{n}_{s}' for s in range(8)) + '};')
    h.insert(-1, '#define BG_BANK(s) (1u + ((s) >> 2))  /* PRG bank to SWITCH_ROM before touching screen s data */')
    (ROOT / 'src/bg_data.h').write_text('\n'.join(h) + '\n')
    (ROOT / 'src/bg_data.c').write_text('\n'.join(c) + '\n')
    (ROOT / 'src/bg_data_a.c').write_text('\n'.join(banks[0]) + '\n')
    (ROOT / 'src/bg_data_b.c').write_text('\n'.join(banks[1]) + '\n')
    print('wrote src/bg_data.c/_a.c/_b.c/.h')
