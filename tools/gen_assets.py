#!/usr/bin/env python3
"""Sprite art for the NES port: Atari PMG shapes -> NES 8x8 sprite tiles + metasprite frames.

Source = the game image (assets/atari/keystone_image_9f80_bfff.bin), decoded as in docs/ATARI_RE_SPEC.md
section 9 (shapes bottom-row-first, per-row colours from page $B9, Kop row mask = colour bit 0):
  Kop    pose p ($20, 1..7): shape $BB00+$BBAD[p], 25 rows; visible if $B900[M+Y]&1,
         colour $B900[M-3+Y], M = $3B ($3E when ducking, p = 7).
  object type t ($75, 1..16): shape $B800+$BC9E[t], $BBB4[t]+1 rows;
         colour $B900[$BCAF[t]+Y] for t = 8,10,11 (pointer moved with the height $71),
         else $B900[$BCAF[t]+1+Y] (thief types 1-5 included).
  Facing: ROM shapes are drawn when Kop $0C bit3 = 0 / object $34 bit3 = 0; bit3 set -> the bit-reversed
         copy at $0300/$0400 = an H-flip at the same X (NES OAM flip).
Pivot of every frame = left edge of the 8 px column at the Atari HPOS (playfield x = HPOS - $30) and
the "feet line": Kop shape row 2 / object shape row 0 (playfield y = 147 - 32*floor - height, see the
header comment of src/spr_data.h).

Output (--emit): src/spr_data.c / src/spr_data.h (the 160 px set used by GBC/DMG),
assets/data/sprites.json (decoded frames + palettes), previews
assets/data/sprites_{kop,thief,obstacles}.png (Atari colours | NES colours, x4) and
assets/data/sprites_chr.png (the CHR sheet).  The NES gets its own widened set in
src/spr_nes.c / spr_nes.h: the same 20 shapes and frame order stretched 8 -> 13 px
(1.6x horizontally, W1 in docs/DECISIONS_PENDING.md), two 8-px sprite columns per row.
--verify DIR...: compare decoded frames with Altirra captures (tools/atari_sprite_probe.py) - PMG column
contents at the predicted rows and screenshot colours at the predicted pixels.

Usage: python tools/gen_assets.py [--emit] [--verify assets/atari/runtime/sprites/kop ...]
"""
import argparse
import itertools
import json
import random
import re
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / 'assets/atari/keystone_image_9f80_bfff.bin'
ATARI_PAL = ROOT / 'assets/data/sprites_atari_palette.bin'   # Altirra NTSC palette, 256 x RGB
BASE = 0x9F80
ROMB = IMG.read_bytes()


def rb(a):
    return ROMB[a - BASE]


# ---------------------------------------------------------------- decode
PF_X0 = 0x30          # HPOS of playfield pixel 0 [V]
PF_Y0 = 39            # PMG row (single-line) of playfield line 0 [V]
FEET_Y0 = 147         # playfield line of the floor-0 feet line [V]

KOP_POSES = {1: 'KOP_WALK1', 2: 'KOP_WALK2', 3: 'KOP_WALK3', 4: 'KOP_WALK4', 5: 'KOP_WALK5',
             6: 'KOP_STAND', 7: 'KOP_DUCK'}
OBJ_TYPES = {1: 'THIEF1', 2: 'THIEF2', 3: 'THIEF3', 4: 'THIEF4', 5: 'THIEF5',
             6: 'RADIO_A', 7: 'RADIO_B', 8: 'BALL', 9: 'CART', 10: 'PLANE_A', 11: 'PLANE_B',
             15: 'SUITCASE', 16: 'MONEYBAG'}
# types 12/13 (3-row shapes at $B8B4/$B8B8) and 14 ($B8D0, runs into table data) are never stored in $75
# by the game code (only 0..11, $0F/$10 and the pickup-collected value 2) -> not exported [H].
WEIGHT = {'KOP': 4.0, 'THIEF': 3.0}


def kop_rows(pose):
    ptr = rb(0xBBAD + pose)
    m = 0x3E if pose == 7 else 0x3B
    rows = []
    for y in range(25):
        vis = rb(0xB900 + m + y) & 1
        rows.append((rb(0xBB00 + ptr + y) if vis else 0, rb(0xB900 + m - 3 + y) & 0xFE))
    return rows, 2          # pivot row = shape row 2 (feet line)


def obj_rows(t):
    ptr = rb(0xBC9E + t)
    h = rb(0xBBB4 + t) + 1
    cb = rb(0xBCAF + t) + (0 if t in (8, 10, 11) else 1)
    return [(rb(0xB800 + ptr + y), rb(0xB900 + cb + y) & 0xFE) for y in range(h)], 0


def all_frames():
    fr = []
    for p, n in KOP_POSES.items():
        rows, piv = kop_rows(p)
        fr.append(dict(name=n, kind='kop', src=p, rows=rows, pivot=piv))
    for t, n in OBJ_TYPES.items():
        rows, piv = obj_rows(t)
        fr.append(dict(name=n, kind='obj', src=t, rows=rows, pivot=piv))
    return fr


def frame_pixels(f):
    """top-down list of 8-px rows of Atari colours (None = transparent), and the top shape row index."""
    rows = f['rows']
    ys = [y for y, (b, _) in enumerate(rows) if b]
    top, bot = max(ys), min(ys)
    pix = []
    for y in range(top, bot - 1, -1):
        b, c = rows[y]
        pix.append([c if (b >> (7 - x)) & 1 else None for x in range(8)])
    return pix, top, bot


# ---------------------------------------------------------------- colours
def atari_rgb():
    p = ATARI_PAL.read_bytes()
    return [tuple(p[i * 3:i * 3 + 3]) for i in range(256)]


NES = [  # 2C02 RGB (same table as tools/gen_bg.py)
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
NES_RGB = {k: np.array(v, float) for k, v in NES}


def _yuv(c):
    r, g, b = (float(v) for v in c)
    y = 0.299 * r + 0.587 * g + 0.114 * b
    return np.array([y, 2.0 * 0.492 * (b - y), 2.0 * 0.877 * (r - y)])   # chroma weighted x2: keep greys grey


def dist(a, b):
    return float(np.sqrt(((_yuv(a) - _yuv(b)) ** 2).sum()))


NEUTRAL = [0x0F, 0x2D, 0x00, 0x10, 0x3D, 0x20]


# ---------------------------------------------------------------- tiles + palettes
def frame_tiles(f):
    """8x8 tiles of a frame (top-aligned to the shape's top row): list of (dy, tile 8x8 of colours/None)."""
    pix, top, bot = frame_pixels(f)
    h = len(pix)
    out = []
    for t0 in range(0, h, 8):
        tile = [pix[t0 + r] if t0 + r < h else [None] * 8 for r in range(8)]
        # dy = playfield offset of the tile's top line from the pivot line (shape row 'pivot')
        out.append((-(top - t0 - f['pivot']), tile))
    return out


def search_palettes(tiles, argb, seed=1):
    """tiles: list of (weight, tile). Returns 4 palettes of 3 NES colour ids minimising weighted RGB error."""
    used = sorted({c for _, t in tiles for row in t for c in row if c is not None})
    cand = set(NEUTRAL)
    for c in used:
        cand.update(k for k, _ in sorted(NES, key=lambda e: dist(e[1], argb[c]))[:3])
    cand = sorted(cand)
    D = {(c, n): dist(argb[c], NES_RGB[n]) for c in used for n in cand}
    hist = []
    for w, t in tiles:
        h = {}
        for row in t:
            for c in row:
                if c is not None:
                    h[c] = h.get(c, 0) + w
        hist.append(h)

    def tcost(h, pal):
        return sum(n * min(D[(c, p)] for p in pal) for c, n in h.items())

    def total(pals):
        return sum(min(tcost(h, p) for p in pals) for h in hist)

    rng = random.Random(seed)
    best = None
    for _ in range(8):
        pals = [[rng.choice(cand) for _ in range(3)] for _ in range(4)]
        cur = total(pals)
        improved = True
        while improved:
            improved = False
            for i, j in itertools.product(range(4), range(3)):
                for c in cand:
                    if c == pals[i][j]:
                        continue
                    old = pals[i][j]
                    pals[i][j] = c
                    v = total(pals)
                    if v < cur - 1e-9:
                        cur, improved = v, True
                    else:
                        pals[i][j] = old
        if best is None or cur < best[0]:
            best = (cur, [list(p) for p in pals])
    return best[1], D


def quantise(tile, pals, D):
    h = {}
    for row in tile:
        for c in row:
            if c is not None:
                h[c] = h.get(c, 0) + 1
    if not h:
        return 0, [[0] * 8 for _ in range(8)]
    pi = min(range(4), key=lambda i: sum(n * min(D[(c, p)] for p in pals[i]) for c, n in h.items()))
    pal = pals[pi]
    q = [[0 if c is None else 1 + min(range(3), key=lambda k: D[(c, pal[k])]) for c in row] for row in tile]
    return pi, q


def chr_bytes(q):
    lo = [sum((q[y][x] & 1) << (7 - x) for x in range(8)) for y in range(8)]
    hi = [sum(((q[y][x] >> 1) & 1) << (7 - x) for x in range(8)) for y in range(8)]
    return [b for pair in zip(lo, hi) for b in pair]     # GB-style interleave, as set_sprite_data wants


def build():
    argb = atari_rgb()
    frames = all_frames()
    ftiles = []
    for f in frames:
        w = WEIGHT['KOP'] if f['kind'] == 'kop' else (WEIGHT['THIEF'] if f['name'].startswith('THIEF') else 1.0)
        ftiles.append([(w, dy, t) for dy, t in frame_tiles(f)])
    pals, D = search_palettes([(w, t) for ft in ftiles for w, _, t in ft], argb)
    chr_list, index = [], {}
    for f, ft in zip(frames, ftiles):
        items = []
        for _, dy, t in ft:
            pi, q = quantise(t, pals, D)
            key = tuple(map(tuple, q))
            fkey = tuple(tuple(r[::-1]) for r in q)
            if key in index:
                ti, flip = index[key], 0
            elif fkey in index:
                ti, flip = index[fkey], 1
            else:
                ti, flip = len(chr_list), 0
                index[key] = ti
                chr_list.append(q)
            items.append(dict(dy=dy, dx=0, tile=ti, pal=pi, flip=flip))
        f['items'] = items
        f['ftiles'] = ft
    return frames, pals, chr_list, argb, D


# ---------------------------------------------------------------- previews
def nes_rgb(n):
    return tuple(int(v) for v in NES_RGB[n])


def preview(frames, pals, chr_list, argb):
    groups = {'kop': [f for f in frames if f['kind'] == 'kop'],
              'thief': [f for f in frames if f['name'].startswith('THIEF')],
              'obstacles': [f for f in frames if f['kind'] == 'obj' and not f['name'].startswith('THIEF')]}
    bgc = (40, 40, 60)
    for g, fl in groups.items():
        cell_h = 32
        im = Image.new('RGB', (len(fl) * 2 * 10 + 4, cell_h + 4), bgc)
        for i, f in enumerate(fl):
            pix, top, bot = frame_pixels(f)
            ox = 2 + i * 20
            oy = 2 + cell_h - 8 - (top - f['pivot'])        # pivot line at cell_h-8
            for r, row in enumerate(pix):
                for x, c in enumerate(row):
                    if c is not None:
                        im.putpixel((ox + x, oy + r), argb[c])
            for it in f['items']:
                q = chr_list[it['tile']]
                for r in range(8):
                    for x in range(8):
                        v = q[r][7 - x if it['flip'] else x]
                        if v:
                            im.putpixel((ox + 10 + x, 2 + cell_h - 8 + it['dy'] + r), nes_rgb(pals[it['pal']][v - 1]))
        im.resize((im.width * 4, im.height * 4), Image.NEAREST).save(ROOT / f'assets/data/sprites_{g}.png')
    n = len(chr_list)
    im = Image.new('RGB', (16 * 9, ((n + 15) // 16) * 9), bgc)
    gray = [(0, 0, 0), (110, 110, 110), (180, 180, 180), (255, 255, 255)]
    for i, q in enumerate(chr_list):
        for r in range(8):
            for x in range(8):
                im.putpixel(((i % 16) * 9 + x, (i // 16) * 9 + r), gray[q[r][x]])
    im.resize((im.width * 4, im.height * 4), Image.NEAREST).save(ROOT / 'assets/data/sprites_chr.png')


# ---------------------------------------------------------------- emit
COPY_MODES = {  # $34&7 -> copies (x offsets from $30 in HPOS units) as drawn by the DLI B2C3-B30F [V 0/4/6]
    0: [0], 4: [0, 0x40], 6: [0, 0x20, 0x40], 7: [0, 0x20],     # 7 only after a radio hit (BEE1)
}


def emit(frames, pals, chr_list):
    names = [f['name'] for f in frames]
    h = ['#ifndef SPR_DATA_H', '#define SPR_DATA_H', '#include <stdint.h>', '#include "platform.h"',
         '#include <gbdk/metasprites.h>   /* platform-neutral dispatcher */',
         '/* generated by tools/gen_assets.py - do not edit.  Spec: docs/ATARI_RE_SPEC.md section 9.',
         ' *',
         ' * Tiles: spr_chr = SPR_NTILES 8x8 tiles, 16 bytes each, GB-style interleaved 2bpp (what GBDK',
         ' *   set_sprite_data() takes on NES too): set_sprite_data(SPR_TILE_BASE, SPR_NTILES, spr_chr).',
         ' *   SPRITES_8x8 mode.  Tile ids in the frames are relative: pass SPR_TILE_BASE as base_tile.',
         ' * Palettes: spr_palettes = 4 sprite palettes x 4 entries (entry 0 = transparent; it is a copy of',
         ' *   bg_pal[0] because $3F10/14/18/1C mirror the backdrop - regenerate after gen_bg.py --emit):',
         ' *   set_sprite_palette(0, 4, spr_palettes).  Each metasprite item carries its palette in props',
         ' *   (GBDK combines base_prop with the item props: pass 0, or 0x20 = behind BG for PRIOR=4 floors).',
         ' * Frames: spr_frame[SPR_F_x][flip] = GBDK metasprite (METASPR_ITEM dy,dx are RELATIVE TO THE',
         ' *   PREVIOUS ITEM, first one to the pivot).  flip = 1 is the mirrored Atari copy ($0300/$0400):',
         ' *   use flip = (kop_0C & 8) for Kop and (obj_34 & 8) for thief/obstacles.  Draw with',
         ' *   move_metasprite_ex(spr_frame[f][flip], SPR_TILE_BASE, prio, oam, x, y)  (prio = 0 or 0x20).',
         ' * Pivot: x = left edge of the Atari 8-px player at HPOS h -> playfield px h - 0x30;',
         ' *   y = feet line: Kop  147 - 32*floor - ($1C & 0x1F)        (Kop shape row 2)',
         ' *                  thief/object 147 - 32*floor + ($71 - 0x1A)  (shape row 0).',
         ' *   NES screen = playfield + camera offset (+ DEVICE_SPRITE_PX_OFFSET_Y).',
         ' */',
         '#define SPR_TILE_BASE 0u   /* engine may move the sprite tiles; frames are base-relative */',
         f'#define SPR_NTILES {len(chr_list)}u',
         '#define SPR_PF_X(hpos) ((uint8_t)((hpos) - 0x30u))',
         '#define SPR_FEET_Y0 147u',
         '#define SPR_FLOOR_DY 32u']
    h.append('enum {')
    for i, n in enumerate(names):
        h.append(f'    SPR_F_{n} = {i},')
    h += [f'    SPR_NFRAMES = {len(names)}', '};',
          'extern const uint8_t spr_chr[SPR_NTILES * 16u];',
          'extern const palette_color_t spr_palettes[16];',
          'extern const metasprite_t *const spr_frame[SPR_NFRAMES][2];',
          'extern const uint8_t spr_frame_ntiles[SPR_NFRAMES];  /* hardware sprites per frame */',
          '/* animation: Kop pose $20 (0..7) -> frame; jump uses pose 2 (= KOP_WALK2), duck = pose 7 */',
          'extern const uint8_t spr_kop_pose[8];',
          '/* object type $75 (0..16) -> frame, 0xFF = nothing drawn (0, 12, 13, 14) */',
          'extern const uint8_t spr_obj_type[17];',
          '/* $34&7 copy layout (DLI B2C3-B30F): number of copies and HPOS offsets from $30.',
          ' * mode 4: 2nd copy at X+$40, but when X >= $A0 it wraps to X-$81 ($34 bit3 = 0) / X-$7A (bit3 = 8).',
          ' * mode 6: radios, X = $58 -> copies at $58/$78/$98; mode 7: X, X+$20 (left after a radio hit;',
          ' * a hit radio is removed by rewriting X/mode from $BEE9/$BEE1, spec 9b). */',
          'extern const uint8_t spr_copy_n[8];',
          'extern const uint8_t spr_copy_dx[8][3];',
          '#endif']
    c = ['#include "spr_data.h"', '/* generated by tools/gen_assets.py - do not edit */']
    chrb = [b for q in chr_list for b in chr_bytes(q)]
    c.append('const uint8_t spr_chr[SPR_NTILES * 16u] = {')
    for i in range(0, len(chrb), 16):
        c.append('  ' + ','.join(f'0x{b:02X}' for b in chrb[i:i + 16]) + ',')
    c.append('};')
    # entry 0 of each sprite palette mirrors the BG backdrop ($3F10 -> $3F00 on the 2C02): copy bg_pal[0]
    bk = 0x0F
    bgc = ROOT / 'src/bg_data.c'
    if bgc.exists():
        txt = bgc.read_text()
        i = txt.find('bg_pal[')
        if i >= 0:
            bk = int(txt[txt.find('{', i) + 1:].split(',')[0].strip(), 0)
    pal = []
    for p in pals:
        pal += [bk] + p
    c.append('const palette_color_t spr_palettes[16] = {' + ','.join(f'0x{v:02X}' for v in pal) + '};')
    for f in frames:
        for flip in (0, 1):
            items = sorted(f['items'], key=lambda it: it['dy'])
            px = py = 0
            parts = []
            comment = []
            for it in items:
                ady, adx = it['dy'], it['dx']
                fl = it['flip'] ^ flip
                props = it['pal'] | (0x40 if fl else 0)
                parts.append(f'METASPR_ITEM({ady - py},{adx - px},{it["tile"]},0x{props:02X})')
                comment.append(f'({ady},{adx})')
                py, px = ady, adx
            c.append(f'/* {f["name"]} flip={flip}: abs (dy,dx) {" ".join(comment)} */')
            c.append(f'static const metasprite_t ms_{f["name"].lower()}_{flip}[] = {{' + ', '.join(parts) +
                     ', METASPR_TERM};')
    c.append('const metasprite_t *const spr_frame[SPR_NFRAMES][2] = {')
    for f in frames:
        n = f['name'].lower()
        c.append(f'  {{ms_{n}_0, ms_{n}_1}},')
    c.append('};')
    c.append('const uint8_t spr_frame_ntiles[SPR_NFRAMES] = {' + ','.join(str(len(f['items'])) for f in frames) + '};')
    kp = [names.index(KOP_POSES.get(p, 'KOP_STAND')) for p in range(8)]
    c.append('const uint8_t spr_kop_pose[8] = {' + ','.join(map(str, kp)) + '};')
    ot = [names.index(OBJ_TYPES[t]) if t in OBJ_TYPES else 0xFF for t in range(17)]
    c.append('const uint8_t spr_obj_type[17] = {' + ','.join(map(str, ot)) + '};')
    cn = [len(COPY_MODES.get(m, [0])) for m in range(8)]
    c.append('const uint8_t spr_copy_n[8] = {' + ','.join(map(str, cn)) + '};')
    c.append('const uint8_t spr_copy_dx[8][3] = {' + ','.join(
        '{' + ','.join(f'0x{v:02X}' for v in (COPY_MODES.get(m, [0]) + [0, 0])[:3]) + '}' for m in range(8)) + '};')
    (ROOT / 'src/spr_data.h').write_text('\n'.join(h) + '\n')
    (ROOT / 'src/spr_data.c').write_text('\n'.join(c) + '\n')


# ---------------------------------------------------------------- NES-only widened set
NES_W = 13      # 8 px Atari player * 1.6 (W1); two 8-px sprite columns per tile row
# The minimap marker tiles are uploaded at OBJ HUD_SPR_T0 (gen_hud.py): the actor tiles must stay below it.
HUD_SPR_H = ROOT / 'src/hud_data.h'
HUD_SPR_T0 = int(re.search(r'#define HUD_SPR_T0\s+(\w+)', HUD_SPR_H.read_text()).group(1).rstrip('uU'), 0) \
    if HUD_SPR_H.exists() else 0x80


OVERRIDES = ROOT / 'assets/data/spr_nes_overrides.json'


def load_overrides():
    """Hand edits from tools/spr_nes_edit.py ({} when the file does not exist)."""
    return json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}


def build_nes(frames, pals, D, ov=None):
    """Widened copies of the same frames: 13 px wide, same pivot (left edge), same frame order.

    The 8 px shape is stretched with src = floor(x*8/13) (the inverse of the renderer's
    screen_x = world_x*8/5, so the 1.6x look matches the background).  Each 8-row tile becomes
    two 8x8 tiles at dx = 0 and dx = 8; the mirrored facing is the mirror of the whole 13 px
    frame, so the tile columns swap.  Tiles are still deduped against their mirrors.

    ov (optional): assets/data/spr_nes_overrides.json from tools/spr_nes_edit.py - per frame and
    facing, the hand-edited palette-index pixels of every tile, with the palette pinned to the one
    the generator gave that tile.
    """
    ov = ov if ov is not None else {}
    idx = [(x * 8) // NES_W for x in range(NES_W)]
    chr_list, index = [], {}

    def tile_of_px(q):
        key = tuple(map(tuple, q))
        if key in index:
            return index[key], 0
        fk = tuple(tuple(r[::-1]) for r in q)
        if fk in index:
            return index[fk], 1
        ti = len(chr_list)
        index[key] = ti
        chr_list.append(q)
        return ti, 0

    def tile_of(rows):
        pi, q = quantise(rows, pals, D)
        ti, fl = tile_of_px(q)
        return ti, fl, pi

    def items_of(sp, top, pivot):
        out = []
        for t0 in range(0, len(sp), 8):
            chunk = sp[t0:t0 + 8]
            chunk = chunk + [[None] * NES_W] * (8 - len(chunk))
            dy = -(top - t0 - pivot)
            for c in range(2):
                tile = [(r[c * 8:(c + 1) * 8] + [None] * 8)[:8] for r in chunk]
                ti, fl, pi = tile_of(tile)
                out.append(dict(dy=dy, dx=c * 8, tile=ti, pal=pi, flip=fl))
        return out

    n_edit = 0
    for f in frames:
        pix, top, bot = frame_pixels(f)
        sp = [[row[i] for i in idx] for row in pix]
        f['nes_items'] = [items_of(sp, top, f['pivot']),
                          items_of([list(reversed(row)) for row in sp], top, f['pivot'])]
        o = ov.get(f['name'])
        if not o:
            continue
        for flip in (0, 1):
            cells = o.get(str(flip))
            if not cells:
                continue
            items = f['nes_items'][flip]
            if len(cells) != len(items):
                raise SystemExit(f'spr_nes_overrides.json: {f["name"]} flip={flip} has {len(cells)} tiles, '
                                 f'the art has {len(items)} - re-run tools/spr_nes_edit.py --export')
            new = []
            for it, c in zip(items, cells):
                if (int(c['dy']), int(c['dx'])) != (it['dy'], it['dx']):
                    raise SystemExit(f'spr_nes_overrides.json: {f["name"]} flip={flip} tile layout changed '
                                     f'- re-run tools/spr_nes_edit.py --export')
                q = [[int(v) & 3 for v in row] for row in c['px']]
                ti, fl = tile_of_px(q)
                new.append(dict(dy=it['dy'], dx=it['dx'], tile=ti, pal=int(c['pal']), flip=fl))
            f['nes_items'][flip] = new
            n_edit += 1
    if n_edit:
        print(f'hand-edited sprite frames applied: {n_edit} (assets/data/spr_nes_overrides.json)')
    return chr_list


def emit_nes(frames, pals, chr_list):
    """src/spr_nes.c/.h: the same symbols as spr_data.h, but 13 px wide (NES build only)."""
    assert len(chr_list) <= HUD_SPR_T0, (f'{len(chr_list)} sprite tiles overlap the HUD marker tiles at '
                                         f'OBJ ${HUD_SPR_T0:02X} (raise HUD_SPR_T0 in gen_hud.py)')
    names = [f['name'] for f in frames]
    h = ['#ifndef SPR_NES_H', '#define SPR_NES_H', '#include <stdint.h>', '#include "platform.h"',
         '#include <gbdk/metasprites.h>   /* platform-neutral dispatcher */',
         '/* generated by tools/gen_assets.py - do not edit.  NES-only widened sprite set (W1):',
         ' * the 20 shapes of src/spr_data.h stretched 8 -> 13 px (1.6x), same frame order, same pivot',
         ' * (left edge at the Atari HPOS = playfield px 0).  Two 8-px sprite columns per tile row,',
         ' * joined through dx = 0 / 8 items, so an actor costs 2 x (rows) hardware sprites.',
         ' * build.ps1 compiles this file *instead of* src/spr_data.c for NES (GBC/DMG keep that one).',
         ' */',
         '#define SPR_TILE_BASE 0u   /* engine may move the sprite tiles; frames are base-relative */',
         f'#define SPR_NTILES {len(chr_list)}u',
         '#define SPR_BANK 3u        /* PRG bank of spr_nes.c (build.ps1 -Wf-bo3): SWITCH_ROM(SPR_BANK)',
         '                            * before reading spr_chr / spr_frame / spr_frame_ntiles */',
         '#define SPR_W 13u          /* widened frame width in px */',
         '#define SPR_PF_X(hpos) ((uint8_t)((hpos) - 0x30u))',
         '#define SPR_FEET_Y0 147u',
         '#define SPR_FLOOR_DY 32u']
    h.append('enum {')
    for i, n in enumerate(names):
        h.append(f'    SPR_F_{n} = {i},')
    h += [f'    SPR_NFRAMES = {len(names)}', '};',
          'extern const uint8_t spr_chr[SPR_NTILES * 16u];',
          'extern const palette_color_t spr_palettes[16];',
          'extern const metasprite_t *const spr_frame[SPR_NFRAMES][2];',
          'extern const uint8_t spr_frame_ntiles[SPR_NFRAMES];  /* hardware sprites per frame */',
          'extern const uint8_t spr_kop_pose[8];',
          'extern const uint8_t spr_obj_type[17];',
          'extern const uint8_t spr_copy_n[8];',
          'extern const uint8_t spr_copy_dx[8][3];',
          '#endif']
    c = ['#include "spr_nes.h"', '/* generated by tools/gen_assets.py - do not edit */']
    chrb = [b for q in chr_list for b in chr_bytes(q)]
    c.append('const uint8_t spr_chr[SPR_NTILES * 16u] = {')
    for i in range(0, len(chrb), 16):
        c.append('  ' + ','.join(f'0x{b:02X}' for b in chrb[i:i + 16]) + ',')
    c.append('};')
    bk = 0x0F
    bgc = ROOT / 'src/bg_data.c'
    if bgc.exists():
        txt = bgc.read_text()
        i = txt.find('bg_pal[')
        if i >= 0:
            bk = int(txt[txt.find('{', i) + 1:].split(',')[0].strip(), 0)
    pal = []
    for p in pals:
        pal += [bk] + p
    c.append('const palette_color_t spr_palettes[16] = {' + ','.join(f'0x{v:02X}' for v in pal) + '};')
    for f in frames:
        for flip in (0, 1):
            items = sorted(f['nes_items'][flip], key=lambda it: (it['dy'], it['dx']))
            px = py = 0
            parts = []
            for it in items:
                props = it['pal'] | (0x40 if it['flip'] else 0)
                parts.append(f'METASPR_ITEM({it["dy"] - py},{it["dx"] - px},{it["tile"]},0x{props:02X})')
                py, px = it['dy'], it['dx']
            c.append(f'static const metasprite_t ms_{f["name"].lower()}_{flip}[] = {{' + ', '.join(parts) +
                     ', METASPR_TERM};')
    c.append('const metasprite_t *const spr_frame[SPR_NFRAMES][2] = {')
    for f in frames:
        n = f['name'].lower()
        c.append(f'  {{ms_{n}_0, ms_{n}_1}},')
    c.append('};')
    c.append('const uint8_t spr_frame_ntiles[SPR_NFRAMES] = {' +
             ','.join(str(len(f['nes_items'][0])) for f in frames) + '};')
    kp = [names.index(KOP_POSES.get(p, 'KOP_STAND')) for p in range(8)]
    c.append('const uint8_t spr_kop_pose[8] = {' + ','.join(map(str, kp)) + '};')
    ot = [names.index(OBJ_TYPES[t]) if t in OBJ_TYPES else 0xFF for t in range(17)]
    c.append('const uint8_t spr_obj_type[17] = {' + ','.join(map(str, ot)) + '};')
    cn = [len(COPY_MODES.get(m, [0])) for m in range(8)]
    c.append('const uint8_t spr_copy_n[8] = {' + ','.join(map(str, cn)) + '};')
    c.append('const uint8_t spr_copy_dx[8][3] = {' + ','.join(
        '{' + ','.join(f'0x{v:02X}' for v in (COPY_MODES.get(m, [0]) + [0, 0])[:3]) + '}' for m in range(8)) + '};')
    (ROOT / 'src/spr_nes.h').write_text('\n'.join(h) + '\n')
    (ROOT / 'src/spr_nes.c').write_text('\n'.join(c) + '\n')


def emit_json(frames, pals, chr_list, argb):
    out = dict(
        source='tools/gen_assets.py from assets/atari/keystone_image_9f80_bfff.bin; spec section 9',
        pivot='x: playfield px = HPOS - 0x30; y: feet line (Kop shape row 2, object row 0)',
        nes_sprite_palettes=[[0x0F] + p for p in pals],
        tables={
            'BC9E_shape_ptr_lo_by_type': [rb(0xBC9E + t) for t in range(17)],
            'BBB4_rows_minus1_by_type': [rb(0xBBB4 + t) for t in range(17)],
            'BCAF_colour_ptr_by_type': [rb(0xBCAF + t) for t in range(17)],
            'BBAD_kop_ptr_by_pose': [rb(0xBBAD + p) for p in range(8)],
            'BE50_floor_row_base': [rb(0xBE50 + f) for f in range(4)],
        },
        frames=[dict(name=f['name'], kind=f['kind'], src=f['src'], pivot_row=f['pivot'],
                     rows_bottom_first=[[b, c] for b, c in f['rows']],
                     nes_items=f['items']) for f in frames],
        ntiles=len(chr_list))
    (ROOT / 'assets/data/sprites.json').write_text(json.dumps(out, indent=1))


# ---------------------------------------------------------------- verification against captures
def flip8(b):
    return int(f'{b:08b}'[::-1], 2)


def verify(dirs, argb):
    inv = {}
    for i in range(0, 256, 2):
        inv.setdefault(argb[i], i)
    frames = all_frames()
    kop = {f['src']: f for f in frames if f['kind'] == 'kop'}
    obj = {f['src']: f for f in frames if f['kind'] == 'obj'}
    tot_ok = tot_n = 0
    pmg_ok = pmg_n = 0
    for d in dirs:
        for rf in sorted(Path(d).glob('*.ram')):
            m = rf.read_bytes()
            im = Image.open(rf.with_suffix('.png')).convert('RGB')
            checks = []        # (label, player page, hpos, rows bottom-first [(byte, colour)], row of Y=0, flip)
            f = (m[0x1D] >> 3) & 3
            h = m[0x1C] & 0x1F
            # the pose drawn this frame is the one whose pointer is in $51 (copied from $65 = last frame's)
            pose = next((p for p in (6, 1, 2, 3, 4, 5, 7) if rb(0xBBAD + p) == m[0x51]), None)
            if pose in kop:
                k = kop[pose]
                checks.append(('kop', 0x0F, m[0x2C + f], k['rows'], 188 - 32 * f - h, bool(m[0x89 + f] & 8), f))
            for fl in range(4):
                t = m[0x75 + fl]
                if t in obj and m[0x30 + fl] > 1:
                    o = obj[t]
                    r0 = 0x3E + rb(0xBE50 + fl) + m[0x71 + fl]
                    mode = m[0x34 + fl] & 7
                    xs = [m[0x30 + fl] + dx for dx in COPY_MODES.get(mode, [0])]
                    for i, x in enumerate(xs):
                        if x < 0xD8:
                            checks.append((f'{o["name"]}#{i}', 0x0C, x, o['rows'], r0,
                                           bool(m[0x34 + fl] & 8), fl))
                # thief drawn with P3 on another floor (AA4B path): $67,f == 1 and P3 X in $2C,f
                if m[0x67 + fl] == 1 and fl != f and 1 <= m[0x63] <= 5:
                    o = obj[m[0x63]]
                    checks.append(('thief(P3)', 0x0F, m[0x2C + fl], o['rows'], 186 - 32 * fl, False, fl))
            rep = []
            for lab, page, x, rows, r0, flip, fl in checks:
                # PMG column check (shape bytes at rows r0 - Y), with or without mirror.  Rows 91-95,
                # 123-127, 155-159 are cleared every frame after drawing (ADFA): skip them.
                # Alternating frames (radio 6/7, plane 10/11) and the ball height may have changed after
                # the draw: also try the sibling frame and +-1 row, keep the best.
                sib = {'RADIO': (6, 7), 'PLANE': (10, 11)}.get(lab[:5])
                pc = [obj[t2]['rows'] for t2 in sib] if sib else [rows]
                n, ok, pd, pf = 0, -999, 0, flip
                # (on the first frame after a turn the drawn copy still has the old facing: try both)
                for rr, ddy, fl in itertools.product(pc, (0, -1, 1), (flip, not flip)):
                    n2 = ok2 = 0
                    for y, (b, _) in enumerate(rr):
                        if not b or (r0 + ddy - y) % 32 in range(27, 32):
                            continue
                        want = flip8(b) if fl else b
                        n2 += 1
                        ok2 += m[page * 0x100 + r0 + ddy - y] == want
                    if ok2 - n2 > ok - n:
                        n, ok, pd, pf = n2, ok2, ddy, fl
                pmg_n += n
                pmg_ok += ok
                # screenshot colours: pixel at HPOS x+bit, PMG row R -> screenshot (2*(x+bit)-88, R-16).
                # The screenshot shows the previous frame (pose/X/height 1 frame behind RAM): search the
                # frames of the same group and a +-4 px / +-2 line window, keep the best.
                if lab == 'kop':
                    cands = [kk['rows'] for kk in kop.values()]
                elif lab.upper().startswith('THIEF'):
                    cands = [obj[t2]['rows'] for t2 in range(1, 6)]
                elif lab.startswith(('RADIO', 'PLANE')):
                    cands = [obj[t2]['rows'] for t2 in ((6, 7) if lab.startswith('RADIO') else (10, 11))]
                else:
                    cands = [rows]
                best = (0, 1, 0, 0)
                for rr, ddx, ddy in itertools.product(cands, range(-4, 5), range(-2, 3)):
                    sn = sok = 0
                    for y, (b, c) in enumerate(rr):
                        if not b:
                            continue
                        bb = flip8(b) if flip else b
                        for bit in range(8):
                            if (bb >> (7 - bit)) & 1:
                                sx, sy = 2 * (x + ddx + bit) - 88, r0 + ddy - y - 16
                                if 0 <= sx < im.width and 0 <= sy < im.height:
                                    sn += 1
                                    sok += inv.get(im.getpixel((sx, sy)), -1) == c
                    if sn and sok / sn > best[0] / best[1]:
                        best = (sok, sn, ddx, ddy)
                tot_ok += best[0]
                tot_n += best[1]
                rep.append(f'{lab}@{x:02X} pmg {ok}/{n}' + (f' dy{pd:+d}' if pd else '') +
                           (' old-facing' if pf != flip else '') +
                           f' scr {best[0]}/{best[1]}' +
                           (f' d({best[2]:+d},{best[3]:+d})' if best[2] or best[3] else ''))
            print(f'{rf.parent.name}/{rf.stem}: ' + '; '.join(rep))
    print(f'TOTAL pmg bytes {pmg_ok}/{pmg_n}, screenshot pixels {tot_ok}/{tot_n}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--emit', action='store_true')
    ap.add_argument('--verify', nargs='*')
    a = ap.parse_args()
    frames, pals, chr_list, argb, D = build()
    print('sprite palettes (NES):', [[f'{v:02X}' for v in p] for p in pals])
    print('tiles', len(chr_list), 'frames', len(frames))
    for f in frames:
        print(f'  {f["name"]:10s} ' + ' '.join(f'(dy{it["dy"]:+d} t{it["tile"]} p{it["pal"]}{" F" if it["flip"] else ""})'
                                             for it in f['items']))
    nes_chr = build_nes(frames, pals, D, load_overrides())
    print('NES wide (13 px) tiles', len(nes_chr), 'worst frame sprites',
          max(len(f['nes_items'][0]) for f in frames))
    preview(frames, pals, chr_list, argb)
    if a.emit:
        emit(frames, pals, chr_list)
        emit_nes(frames, pals, nes_chr)
        emit_json(frames, pals, chr_list, argb)
        print('wrote src/spr_data.c/.h (GBC/DMG), src/spr_nes.c/.h (NES wide), assets/data/sprites.json,'
              ' assets/data/sprites_*.png')
    if a.verify is not None:
        verify(a.verify, argb)


if __name__ == '__main__':
    main()
