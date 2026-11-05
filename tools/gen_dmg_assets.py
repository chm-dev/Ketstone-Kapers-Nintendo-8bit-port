#!/usr/bin/env python3
"""DMG (original Game Boy, 4 grey shades) assets for the Keystone Kapers port: the DMG path of the one
GB ROM (build_gbc.ps1; main_gbc.c uses this data when _cpu != CGB_TYPE).

Reuses the Atari image pipeline of tools/gen_gbc_assets.py (its source up to the preview section is
exec'd: same crop 160x181, object cleanup, minimap box erased, escalator phases, elevator car states).
Backgrounds (DECISIONS_PENDING U2): light playfield, dark actors.  Atari colour -> shade by an explicit
  table (BG_SHADE: walls/sky/street white, floors/pillars light grey) plus context rules: dark scenery
  lines (DARK_OBJ) dark grey when thin, light grey with a dark outline when wide; dark green bodies light
  grey; skyline = light grey outline + sparse dots on white; escalator belts light grey with white
  stripes; dark grey bottom line per floor slab.  Tiles deduplicated per screen WITHOUT flips (a DMG BG
  tile has no flip bits), animated states included so every tile of every state is in VRAM.
  Map ids = DMG_TILE_BASE + tile (HUD tiles come first).
VRAM budget (384 tiles, one bank): OBJ ids 0..127 at $8000 = sprites (41 tiles) + marker tiles;
  BG ids 0..127 at $9000 and 128..255 at $8800 (GBDK default BG8800 mode) = HUD tiles (ids 0..60) +
  the current screen's tiles (ids 61..255).  OBJ ids 128..255 share $8800 with the BG: unused.
Sprites: src/spr_data.c tile data baked per actor (black for its darkest colours up to SPR_BLACK_SHARE
  of its pixels, the rest dark grey; no light sprite fills), so one OBP0 serves all frames; OBP1 =
  identity for the minimap car marker.  A contrast check places every actor on every floor of every
  screen and fails unless its dominant shade is >= 2 darker than the wall/floor/skyline under it.
HUD: dark band (BGP identity: 5x7 font white on black), hat, minimap cut from the Atari composite with the
  old luma thresholds (MAP_LIMITS), 2 marker tiles.  Sound: the GBC tables (src/gbc/gbc_data.c).
Banks: from GBC_ROM_BANKS (src/gbc/gbc_data.h) up - re-run after gen_gbc_assets.py --emit.
Output: src/dmg/dmg_data.h, dmg_data.c (bank 0 tables), dmg_bank<N>.c, assets/data/dmg_preview.png
  (Atari | DMG per state), assets/data/dmg_scene_preview.png (actors on every screen + HUD band).
Usage: python -I tools/gen_dmg_assets.py [--emit]   (re-run after gen_assets.py --emit: fingerprint of spr_data.c)
"""
import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'src/dmg'
BANK_BYTES = 16000

ap = argparse.ArgumentParser()
ap.add_argument('--emit', action='store_true')
args = ap.parse_args()

# ---- reuse the GBC script's image pipeline (definitions + module-level file reads only)
_src = (ROOT / 'tools/gen_gbc_assets.py').read_text().split('previews = []')[0]
_argv = sys.argv
sys.argv = ['gen_gbc_assets.py']
G = {'__file__': str(ROOT / 'tools/gen_gbc_assets.py'), '__name__': 'gen_gbc_assets'}
exec(compile(_src, 'gen_gbc_assets.py', 'exec'), G)
sys.argv = _argv
composite, colbk_mask, esc_phase, car_img = G['composite'], G['colbk_mask'], G['esc_phase'], G['car_img']
GREEN, CAR_TX, CAR_Y0 = G['GREEN'], G['CAR_TX'], G['CAR_Y0']
TW, TH, lum, chr_bytes = G['TW'], G['TH'], G['lum'], G['chr_bytes']
import re
NES = {int(i, 16): (int(r), int(g), int(b)) for i, r, g, b in re.findall(
    r'\((0x[0-9A-Fa-f]{2}),\s*\((\d+),\s*(\d+),\s*(\d+)\)\)', (ROOT / 'tools/gen_bg.py').read_text())}


def c_array(src, name):
    m = re.search(r'\b%s\[[^\]]*\]\s*=\s*\{(.*?)\};' % name, src, re.S)
    return [int(x, 0) for x in re.findall(r'0x[0-9A-Fa-f]+|\d+', m.group(1))]


# ---------------------------------------------------------------- shades
# shade 0 white .. 3 black (BGP identity).  Light background, dark actors (DECISIONS_PENDING U2):
#   the playfield uses shades 0-1 for every fill (walls, sky, skyline, floors, street) and shade 2 only
#   for thin edges (outlines of the dark scenery, pillar caps, the bottom line of each floor slab), so the
#   sprites (shades 2-3, mostly 3) stay >= 2 shades darker than what they stand in front of.
#   Not monotonic in luma (green wall 56 -> white, skyline 61 -> light grey): an explicit colour table.
BG_SHADE = {
    (106, 124, 244): 0,                                     # sky
    (153, 111, 241): 0, (210, 93, 169): 0, (214, 96, 114): 0, (200, 109, 57): 0, (170, 126, 0): 0,   # sunset
    (62, 60, 63): 0,                                        # skyline: white + light grey outline and dots (below)
    (0, 95, 0): 0,                                          # green wall (dominant fill)
    (127, 142, 0): 1, (98, 117, 0): 1,                      # floor slabs (olive)
    (131, 126, 133): 0,                                     # street; roof items (sky zone)
    (103, 100, 106): 2,                                     # pillar caps / bases (edges); roof items: 0 (sky zone)
    (205, 198, 210): 1, (170, 164, 173): 1,                 # pillars (stripe white + shading); escalator stripes: 0
    (0, 130, 103): 0, (127, 255, 246): 2,                   # elevator car open (teal) + its lit top (a dark lintel)
}
DARK_OBJ = {(0, 0, 0), (0, 2, 0), (0, 18, 0)}   # black lines / dark scenery: thin -> dark grey, wide -> light fill + dark outline
BODY = {(7, 42, 0): 1, (0, 59, 0): 1}            # dark green bodies (counters, umbrellas): light grey, no outline
OBJ_FILL, OBJ_EDGE = 1, 2
SKY_ZONE = 51                  # rows above the roof slab (skyline, roof items)
SKYLINE = (62, 60, 63)
SKY_EDGE = 1                   # skyline silhouette: light grey outline where it meets the sky ...
SKY_DOTS = 1                   # ... and a sparse dot pattern inside (1 pixel in 4), the rest white
ROOF_ITEM = 1                  # roof items (street grey / grey shadow in the sky zone)
FLOOR_EDGE = 2                 # last row of each floor slab (olive 98,117,0 above a non-olive row)
OLIVE2 = (98, 117, 0)
# minimap (dark HUD band, unchanged look): the old luma thresholds
MAP_LIMITS = (45, 80, 130)


def luma_shade(c, limits=MAP_LIMITS):
    l = lum(c)
    for i, lim in enumerate(limits):
        if l < lim:
            return 3 - i
    return 0


def shade_img(img, colbk=None):
    """Atari RGB image (H x 160) -> shades (H x 160).  colbk: escalator belt mask (screens 0/7)."""
    h, w = img.shape[:2]
    keys = img[..., 0].astype(np.int32) << 16 | img[..., 1].astype(np.int32) << 8 | img[..., 2]
    cols = {}
    for k in np.unique(keys):
        c = (int(k) >> 16, (int(k) >> 8) & 255, int(k) & 255)
        cols[int(k)] = c
    out = np.zeros((h, w), np.uint8)
    obj = np.zeros((h, w), bool)
    for k, c in cols.items():
        m = keys == k
        if c in DARK_OBJ:
            obj |= m
        elif c in BODY:
            out[m] = BODY[c]
        elif c in BG_SHADE:
            out[m] = BG_SHADE[c]
        else:
            raise SystemExit(f'gen_dmg_assets.py: no DMG shade for Atari colour {c} (add it to BG_SHADE / DARK_OBJ)')
    # dark scenery: interior light grey, edge (4-neighbour outside the object) dark grey
    pad = np.pad(obj, 1, constant_values=False)
    inner = pad[:-2, 1:-1] & pad[2:, 1:-1] & pad[1:-1, :-2] & pad[1:-1, 2:]
    out[obj] = OBJ_EDGE
    out[obj & inner] = OBJ_FILL
    def mask(c):
        return keys == (c[0] << 16 | c[1] << 8 | c[2])

    # sky zone: roof items (street grey, grey shadow): white with a light grey outline (actors on the roof
    # stand in front of them)
    ri = mask((131, 126, 133)) | mask((103, 100, 106))
    ri[SKY_ZONE:] = False
    pr = np.pad(ri, 1, constant_values=False)
    ri_in = pr[:-2, 1:-1] & pr[2:, 1:-1] & pr[1:-1, :-2] & pr[1:-1, 2:]
    out[ri] = ROOF_ITEM
    out[ri & ri_in] = 0
    # skyline: outline against the sky / sunset (4-neighbours) + sparse dots, white otherwise
    sk = mask(SKYLINE)
    sk[SKY_ZONE:] = False
    sky = np.zeros((h, w), bool)
    for c in [c for c, v in BG_SHADE.items() if v == 0 and c not in ((0, 95, 0), (131, 126, 133), (0, 130, 103), SKYLINE)]:
        sky |= mask(c)
    sky[SKY_ZONE:] = False
    ps = np.pad(sky, 1, constant_values=False)
    edge = sk & (ps[:-2, 1:-1] | ps[2:, 1:-1] | ps[1:-1, :-2] | ps[1:-1, 2:])
    yy, xx = np.mgrid[0:h, 0:w]
    dots = sk & ((xx + 2 * yy) % 4 == 0)
    out[dots] = SKY_DOTS
    out[edge] = SKY_EDGE
    # escalator belts: the green belt light grey, the moving stripes white (as on the Atari: stripes lighter)
    if colbk is not None:
        g = (keys == (0 << 16 | 95 << 8 | 0)) & colbk
        out[g] = 1
        s = (keys == (205 << 16 | 198 << 8 | 210)) & colbk
        out[s] = 0
    # bottom line of each floor slab
    o2 = keys == (OLIVE2[0] << 16 | OLIVE2[1] << 8 | OLIVE2[2])
    below = np.zeros_like(o2)
    below[:-1] = o2[1:]
    out[o2 & ~below] = FLOOR_EDGE
    return out


def blocks(sh):
    return {(tx, ty): sh[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8] for ty in range(TH) for tx in range(TW)}


class Tiles:
    def __init__(self):
        self.list, self.index = [], {}

    def add(self, t):
        k = t.tobytes()
        if k not in self.index:
            self.index[k] = len(self.list)
            self.list.append(t)
        return self.index[k]


# ---------------------------------------------------------------- screens
class Scr:
    def __init__(self, base, variants, colbk=None):
        self.tiles = Tiles()
        self.atari = base
        self.shaded = shade_img(base, colbk)
        self.base = {p: self.tiles.add(b) for p, b in blocks(self.shaded).items()}
        self.var = {k: {p: self.tiles.add(b) for p, b in blocks(shade_img(v, colbk)).items()} for k, v in variants.items()}

    def render(self, q):
        pix = np.zeros((192, 160), np.uint8)
        for (tx, ty), tid in q.items():
            pix[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8] = self.tiles.list[tid]
        return pix


screens, previews = [], []
for s in range(8):
    base = composite(s)
    variants = {}
    colbk = None
    if s in (0, 7):
        colbk = colbk_mask(s)
        eb = base.copy()
        eb[colbk] = GREEN
        ph = [esc_phase(s, eb, k, colbk) for k in range(4)]
        base = ph[0]
        for k in range(1, 4):
            variants[f'ph{k}'] = ph[k]
    if s == 4:
        for f in range(3):
            for st in (1, 2):
                variants[f'f{f}s{st}'] = car_img(base, f, st)
    sc = Scr(base, variants, colbk)
    screens.append(sc)
    previews.append((base, sc.render(sc.base)))
    for k in ('ph2', 'f0s2', 'f2s1'):
        if k in variants:
            q = dict(sc.base)
            q.update(sc.var[k])
            previews.append((variants[k], sc.render(q)))

# ---------------------------------------------------------------- dynamic data
TILE_BASE = None   # set after the HUD
esc = {}
for s in (0, 7):
    sc = screens[s]
    allq = [sc.base] + [sc.var[f'ph{k}'] for k in range(1, 4)]
    dyn = [(tx, ty) for ty in range(TH) for tx in range(TW) if any(q[(tx, ty)] != allq[0][(tx, ty)] for q in allq[1:])]
    runs = []
    for (tx, ty) in dyn:
        if runs and runs[-1][1] == ty and runs[-1][0] + runs[-1][2] == tx:
            runs[-1][2] += 1
        else:
            runs.append([tx, ty, 1])
    esc[s] = (runs, allq)
sc4 = screens[4]
elev = []                                  # [floor][state][4 tile ids]
for f in range(3):
    ty0 = CAR_Y0[f] // 8
    for st in range(3):
        q = sc4.base if st == 0 else sc4.var[f'f{f}s{st}']
        elev.append([q[(CAR_TX, ty0 + i)] for i in range(4)])
    for st in (1, 2):
        q = sc4.var[f'f{f}s{st}']
        bad = [p for p in q if q[p] != sc4.base[p] and not (p[0] == CAR_TX and ty0 <= p[1] < ty0 + 4)]
        assert not bad, bad

# ---------------------------------------------------------------- HUD tiles (idx 0 white .. 3 black)
import importlib.util
spec = importlib.util.spec_from_file_location('gen_hud', ROOT / 'tools/gen_hud.py')
gen_hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen_hud)
GL, ORDER = gen_hud.G, gen_hud.ORDER


def glyph(ch):
    t = np.full((8, 8), 3, np.uint8)
    for r, row in enumerate(GL[ch]):
        for c, b in enumerate(row):
            if b == '1':
                t[r, c + 1] = 0
    return t


HAT = np.array([[int(ch) for ch in row] for row in
                ["33333333", "33300333", "33000033", "33000033", "30000003", "30000003", "00000000", "33333333"]], np.uint8)
hud = [glyph(ch) for ch in ORDER] + [HAT]
HT_HAT = len(hud) - 1
raw = G['pf_of'](G['SCR'] / 'screen_0.png').copy()
mm = raw[155:171, 40:120].copy()
mm[G['eq'](mm, G['SPECK'])] = GREEN
mm[G['eq'](mm, G['GREY'])] = G['DARK']
HT_MAP = len(hud)
msh = np.array([[luma_shade(tuple(int(v) for v in p)) for p in row] for row in mm], np.uint8)
for ty in range(2):
    for tx in range(10):
        hud.append(msh[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8].copy())
TILE_BASE = len(hud)
for s, sc in enumerate(screens):
    n = len(sc.tiles.list)
    print(f'screen {s}: {n} tiles (ids {TILE_BASE}..{TILE_BASE + n - 1})')
    assert TILE_BASE + n <= 256, f'screen {s}: {TILE_BASE + n} BG tiles exceed 256'
mx = max(len(sc.tiles.list) for sc in screens)

# ---------------------------------------------------------------- sprites
src = (ROOT / 'src/spr_data.c').read_text()
chr_b = c_array(src, 'spr_chr')
NT = len(chr_b) // 16
spr_tiles = []
for t in range(NT):
    a = np.zeros((8, 8), np.uint8)
    for y in range(8):
        lo, hi = chr_b[t * 16 + y * 2], chr_b[t * 16 + y * 2 + 1]
        for x in range(8):
            a[y, x] = ((lo >> (7 - x)) & 1) | (((hi >> (7 - x)) & 1) << 1)
    spr_tiles.append(a)
import re
tile_pal, tile_grp = {}, {}
for m in re.finditer(r'ms_(\w+)\[\] = \{(.*?)\};', src):
    grp = re.match(r'[a-z]+', m.group(1)).group(0)          # kop, thief, radio, ball, cart, plane, suitcase, moneybag
    for t, p in re.findall(r'METASPR_ITEM\(-?\d+,-?\d+,(\d+),(0x[0-9A-Fa-f]+)\)', m.group(2)):
        pal = int(p, 16) & 3
        assert tile_pal.setdefault(int(t), pal) == pal, f'sprite tile {t} used with two palettes'
        assert tile_grp.setdefault(int(t), grp) == grp, f'sprite tile {t} shared by {grp} and {tile_grp[int(t)]}'
assert set(tile_pal) == set(range(NT)), set(range(NT)) - set(tile_pal)
spr_pal = c_array(src, 'spr_palettes')
# per actor: colour slots (palette, idx) darkest first become black until black is >= SPR_BLACK_SHARE of the
# actor's pixels (over its frames), the rest dark grey; skin (NES $27) stays dark grey so faces read; the
# thief keeps only his darkest colour black (black / dark grey stripes).  No white/light sprite fills.
SPR_BLACK_SHARE = 0.5
SKIN = 0x27
ONLY_DARKEST = {'thief'}
cnt = {}
for m in re.finditer(r'ms_(\w+)_0\[\] = \{(.*?)\};', src):
    for t, p in re.findall(r'METASPR_ITEM\(-?\d+,-?\d+,(\d+),(0x[0-9A-Fa-f]+)\)', m.group(2)):
        t = int(t)
        for k in (1, 2, 3):
            key = (tile_grp[t], tile_pal[t], k)
            cnt[key] = cnt.get(key, 0) + int((spr_tiles[t] == k).sum())
slot_shade = {}                    # (group, palette, colour slot 1..3) -> shade
for g in sorted(set(tile_grp.values())):
    slots = sorted([(k, n) for k, n in cnt.items() if k[0] == g and n],
                   key=lambda kn: lum(NES[spr_pal[kn[0][1] * 4 + kn[0][2]]]))
    total, black = sum(n for _, n in slots), 0
    for i, (k, n) in enumerate(slots):
        nes = spr_pal[k[1] * 4 + k[2]]
        if i == 0 or (black < SPR_BLACK_SHARE * total and nes != SKIN and g not in ONLY_DARKEST):
            slot_shade[k] = 3
            black += n
        else:
            slot_shade[k] = 2
    print(f'sprite {g}: black {black}/{total} px;', ', '.join(f'NES ${spr_pal[k[1] * 4 + k[2]]:02X}->{slot_shade[k]}' for k, _ in slots))
OBP0_SHADE = {1: 0, 2: 2, 3: 3}    # OBP0 idx -> shade (idx 0 transparent; idx 1 white = Kop's minimap marker only)
IDX_OF = {v: k for k, v in OBP0_SHADE.items()}
spr_out = []
for t, a in enumerate(spr_tiles):
    b = a.copy()
    for k in (1, 2, 3):
        b[a == k] = IDX_OF[slot_shade.get((tile_grp[t], tile_pal[t], k), 2)]
    spr_out.append(b)
OBP0 = sum(OBP0_SHADE[k] << (2 * k) for k in (1, 2, 3))
OBP0_DOC = ', '.join(f'idx {k} {("white", "light grey", "dark grey", "black")[OBP0_SHADE[k]]}' for k in (1, 2, 3))
OBP1 = 0xE4
BGP = 0xE4
marker = [np.zeros((8, 8), np.uint8), np.zeros((8, 8), np.uint8)]
marker[0][0:2, 0:2] = 1                  # OBP0 idx 1 = white (Kop) / OBP1 idx 1 = light grey (car)
marker[1][0:2, 0:2] = 3                  # idx 3 = black in both (thief)
print('sprite tiles', NT, 'marker tiles 2; OBP0', hex(OBP0))
bud = {'BG ids': TILE_BASE + mx, 'OBJ ids': NT + 2}
print('VRAM budget: BG ids used up to %d of 256 (HUD %d + worst screen %d), OBJ %d of 128, %d of 384 tiles in use' % (
    bud['BG ids'], TILE_BASE, mx, bud['OBJ ids'], bud['BG ids'] + bud['OBJ ids']))

# ---------------------------------------------------------------- contrast check: actors on the shaded screens
# Every frame (first of each actor) placed on every floor of every screen at fixed x; the sprite's dominant
# shade must be >= 2 darker than the dominant background shade under its pixels (DECISIONS_PENDING U2).
frames = []
for m in re.finditer(r'ms_(\w+)_0\[\] = \{(.*?)\};', src):
    items = [(int(a), int(b), int(t)) for a, b, t, _ in
             re.findall(r'METASPR_ITEM\((-?\d+),(-?\d+),(\d+),(0x[0-9A-Fa-f]+)\)', m.group(2))]
    frames.append((m.group(1), items))
PLACE = [('kop_stand', 6), ('thief1', 24), ('radio_a', 44), ('ball', 62), ('cart', 78), ('plane_a', 96),
         ('suitcase', 114), ('moneybag', 134)]
FEET_Y0, FLOOR_DY = 147, 32


def sprite_pixels(name):
    items = dict(frames)[name]
    px, y, x = [], 0, 0
    for dy, dx, t in items:
        y += dy
        x += dx
        for yy in range(8):
            for xx in range(8):
                v = spr_out[t][yy, xx]
                if v:
                    px.append((y + yy, x + xx, OBP0_SHADE[int(v)]))
    return px


# structural background = walls, floors, sky, skyline, street (scenery props such as counters, pillars,
# escalators are crossed briefly and only reported)
STRUCT = [(0, 95, 0), (127, 142, 0), (98, 117, 0), SKYLINE, (131, 126, 133)] + \
         [c for c, v in BG_SHADE.items() if v == 0 and c not in ((0, 130, 103), (205, 198, 210))]
MIN_SHARE = 0.4               # and at least this share of its pixels >= 2 darker than the pixel under them
scenes, worst, fails = [], [], []
for s, sc in enumerate(screens):
    pix = sc.shaded.copy()
    st = np.zeros(sc.shaded.shape, bool)
    for c in STRUCT:
        st |= (sc.atari == np.array(c, np.uint8)).all(-1)
    for f in range(4):
        for name, x0 in PLACE:
            y0 = FEET_Y0 - FLOOR_DY * f
            sp = sprite_pixels(name)
            on = [(int(sc.shaded[y0 + y, x0 + x]), v) for y, x, v in sp if st[y0 + y, x0 + x]]
            shs = [v for _, _, v in sp]
            dom_s = max(set(shs), key=shs.count)
            if len(on) >= len(sp) // 2:
                bgs = [b for b, _ in on]
                dom_b = max(set(bgs), key=bgs.count)
                frac = sum(1 for b, v in on if v - b >= 2) / len(on)
                worst.append((frac, s, f, name, dom_s, dom_b))
                if dom_s - dom_b < 2 or frac < MIN_SHARE:
                    fails.append(f'screen {s} floor {f} {name}: sprite shade {dom_s} on background {dom_b}, {frac:.0%} of pixels >= 2 darker')
            for (y, x, v) in sp:
                pix[y0 + y, x0 + x] = v
    scenes.append(pix)
# per row, every frame of every actor: a sprite row over light grey structure (floor slab, roof items)
# must be mostly black (dark grey would be only 1 shade off)
row_checks = 0
for s, sc in enumerate(screens):
    st = np.zeros(sc.shaded.shape, bool)
    for c in STRUCT:
        st |= (sc.atari == np.array(c, np.uint8)).all(-1)
    olive = np.zeros(st.shape, bool)
    for c in ((127, 142, 0), OLIVE2):
        olive |= (sc.atari == np.array(c, np.uint8)).all(-1)
    st &= ~olive | (olive.mean(1) > 0.6)[:, None]          # olive counts only in the floor slab rows (not on props)
    st &= ~((sc.atari == np.array((0, 95, 0), np.uint8)).all(-1) & (sc.shaded == 1))   # escalator belts (props)
    st[:SKY_ZONE] &= ~(sc.atari[:SKY_ZONE] == np.array((131, 126, 133), np.uint8)).all(-1)   # roof items (props)
    bgv = sc.shaded.copy()
    bgv[(sc.atari == np.array(SKYLINE, np.uint8)).all(-1)] = 0   # skyline = white fill (outline + 1-in-4 dots)
    for name, _ in frames:
        sp = sprite_pixels(name)
        for f in range(4):
            for x0 in range(0, 152, 8):
                y0 = FEET_Y0 - FLOOR_DY * f
                rows = {}
                for y, x, v in sp:
                    if st[y0 + y, x0 + x]:
                        rows.setdefault(y, []).append((int(bgv[y0 + y, x0 + x]), v))
                for y, px in rows.items():
                    if sum(1 for b, _ in px if b == 1) * 2 > len(px) and len(px) >= 2:
                        row_checks += 1
                        vs = [v for b, v in px if b == 1]
                        if sum(1 for v in vs if v == 3) * 2 < len(vs):
                            fails.append(f'screen {s} floor {f} x{x0} {name} row {y}: {vs} on light grey')
print(f'contrast rows: {row_checks} sprite rows over light grey checked')
worst.sort()
print(f'contrast: {len(worst)} actor placements on walls/floors/skyline; lowest share of >=2-darker pixels:',
      ', '.join(f'{n} s{s} f{f} {fr:.0%}' for fr, s, f, n, _, _ in worst[:4]))
assert not fails, 'DMG contrast rule broken:\n  ' + '\n  '.join(fails)

FINGERPRINT = hashlib.sha1((ROOT / 'src/spr_data.c').read_bytes().replace(b'\r\n', b'\n')).hexdigest()[:16]

# ---------------------------------------------------------------- preview
sh_rgb = np.array([(236, 238, 236), (160, 160, 160), (84, 84, 84), (0, 0, 0)], np.uint8)
Wd = 160 * 2 + 8
pv = Image.new('RGB', (Wd * 3, 200 * ((len(previews) + 2) // 3) + 40), (40, 40, 40))
for i, (a, n) in enumerate(previews):
    x, y = (i % 3) * Wd, (i // 3) * 200
    pv.paste(Image.fromarray(a), (x, y))
    pv.paste(Image.fromarray(sh_rgb[n]), (x + 164, y))
hrow = np.zeros((16, 160), np.uint8)
for i in range(20):
    hrow[(i // 10) * 8:(i // 10) * 8 + 8, (i % 10) * 8:(i % 10) * 8 + 8] = hud[HT_MAP + i]
pv.paste(Image.fromarray(sh_rgb[hrow]).resize((320, 32), Image.NEAREST), (0, pv.height - 36))
pv.save(ROOT / 'assets/data/dmg_preview.png')
print('wrote assets/data/dmg_preview.png (Atari | DMG per state)')
# actors on every screen (playfield lines 23..158 = what the camera can show), 2x, 4 x 2 grid + HUD band
sp = Image.new('RGB', (4 * 328, 2 * 280 + 40), (40, 40, 40))
for s, pix in enumerate(scenes):
    im = Image.fromarray(sh_rgb[pix[23:159]]).resize((320, 272), Image.NEAREST)
    sp.paste(im, ((s % 4) * 328, (s // 4) * 280))
hb = np.full((16, 160), 3, np.uint8)
hb[:, :80] = hrow[:, :80]
for i, ch in enumerate('123400 T50'):
    hb[0:8, 80 + i * 8:88 + i * 8] = hud[ORDER.index(ch)]
sp.paste(Image.fromarray(sh_rgb[hb]).resize((320, 32), Image.NEAREST), (0, 2 * 280 + 4))
sp.save(ROOT / 'assets/data/dmg_scene_preview.png')
print('wrote assets/data/dmg_scene_preview.png (actors on every screen, DMG shades)')

# ---------------------------------------------------------------- emit
if args.emit:
    OUT.mkdir(exist_ok=True)

    def arr(name, vals, per=16, typ='uint8_t'):
        out = [f'const {typ} {name}[] = {{']
        for i in range(0, len(vals), per):
            out.append('  ' + ','.join(str(v) for v in vals[i:i + per]) + ',')
        return out + ['};']

    # one ROM with the GBC data (build_gbc.ps1): the DMG banks follow the GBC ones; HUD tile ids are shared
    ghdr = (ROOT / 'src/gbc/gbc_data.h').read_text()
    gdef = {k: int(v) for k, v in re.findall(r'#define (GBC_\w+) (\d+)u', ghdr)}
    FIRST_BANK = gdef['GBC_ROM_BANKS']
    for k, v in (('GBC_HUD_NTILES', len(hud)), ('GBC_HT_SPACE', 36), ('GBC_HT_HAT', HT_HAT), ('GBC_HT_MAP', HT_MAP),
                 ('GBC_BG_W', TW), ('GBC_BG_H', TH), ('GBC_ELEV_TX', CAR_TX)):
        assert gdef[k] == v, f'{k}: gbc_data.h {gdef[k]} != DMG {v} (main_gbc.c uses one set)'
    hud_bytes = [b for t in hud for b in chr_bytes(t)]
    spr_bytes = [b for t in spr_out for b in chr_bytes(t)]
    banks, bank, used = {}, FIRST_BANK, 0
    items = [('hud', len(hud_bytes) + len(spr_bytes))] + [(s, len(screens[s].tiles.list) * 16 + TW * TH + 64 + 200) for s in range(8)]
    for key, n in items:
        if used + n > BANK_BYTES:
            bank, used = bank + 1, 0
        banks[key] = bank
        used += n
    nbanks = bank
    files = {b: ['#include "dmg_data.h"', '/* generated by tools/gen_dmg_assets.py - do not edit */']
             for b in range(FIRST_BANK, nbanks + 1)}
    files[banks['hud']] += arr('dmg_hud_chr', hud_bytes) + arr('dmg_spr_chr', spr_bytes)
    for s, sc in enumerate(screens):
        f = files[banks[s]]
        f += arr(f'dmg_chr_{s}', [b for t in sc.tiles.list for b in chr_bytes(t)])
        f += arr(f'dmg_map_{s}', [TILE_BASE + sc.base[(tx, ty)] for ty in range(TH) for tx in range(TW)], TW)
        if s in esc:
            runs, allq = esc[s]
            v = [len(runs)]
            for tx, ty, w in runs:
                v += [tx, ty, w]
                for q in allq:
                    v += [TILE_BASE + q[(tx + i, ty)] for i in range(w)]
            f += arr(f'dmg_esc_{s}', v)
    files[banks[4]] += arr('dmg_elev', [TILE_BASE + t for st in elev for t in st], 4)

    h = ['#ifndef DMG_DATA_H', '#define DMG_DATA_H', '#include <stdint.h>',
         '/* generated by tools/gen_dmg_assets.py - do not edit.  DMG (4 shades) screen/HUD/sprite data of the one GB ROM',
         ' * (main_gbc.c uses it when _cpu != CGB_TYPE).  Shares with src/gbc/gbc_data.h: GBC_BG_W/H, GBC_ELEV_TX, gbc_elev_ty,',
         ' * GBC_HUD_NTILES and the GBC_HT_* ids (asserted equal by the generator).',
         ' * Banked arrays: SWITCH_ROM(dmg_bank[s]) first.  Tile ids in the maps are final (HUD ids 0..%d, screen tiles from DMG_TILE_BASE). */' % (TILE_BASE - 1),
         f'#define DMG_FIRST_BANK {FIRST_BANK}u     /* = GBC_ROM_BANKS when generated (build_gbc.ps1 checks it) */',
         f'#define DMG_ROM_BANKS {nbanks + 1}u      /* banks 0..{nbanks} used */',
         f'#define DMG_SRC_FINGERPRINT "{FINGERPRINT}"  /* sha1 of src/spr_data.c (build_gbc.ps1 checks it) */',
         f'#define DMG_TILE_BASE {TILE_BASE}u     /* first BG id of a screen\'s tiles */',
         f'#define DMG_BGP {BGP}u',
         f'#define DMG_OBP0 {OBP0}u               /* sprites: {OBP0_DOC} */',
         f'#define DMG_OBP1 {OBP1}u',
         'extern const uint8_t dmg_bank[8];',
         'extern const uint8_t dmg_ntiles[8];',
         'extern const uint8_t *const dmg_chr[8];',
         'extern const uint8_t *const dmg_map[8];',
         '/* escalators (screens 0, 7): count, then per run tx, ty, w, and per phase 0..3: w tile ids */',
         'extern const uint8_t *const dmg_esc[8];        /* 0 = none */',
         'extern const uint8_t dmg_elev[];               /* [floor][state 0 closed,1 moving,2 open][4 ids] (bank dmg_bank[4]) */',
         f'#define DMG_HUD_BANK {banks["hud"]}u',
         '#define DMG_MARK_TILE_A 0x7Eu             /* OBJ ids: marker idx 1 (Kop white, car light grey) */',
         '#define DMG_MARK_TILE_B 0x7Fu             /* marker idx 3 (thief black) */',
         'extern const uint8_t dmg_hud_chr[];      /* bank DMG_HUD_BANK, GBC_HUD_NTILES tiles */',
         f'extern const uint8_t dmg_spr_chr[{NT * 16}];  /* bank DMG_HUD_BANK: spr_data.c tiles baked to OBP0 idx */',
         'extern const uint8_t dmg_marker_chr[32];',
         '#endif']
    for s in range(8):
        h.insert(-1, f'extern const uint8_t dmg_chr_{s}[], dmg_map_{s}[];')
    for s in esc:
        h.insert(-1, f'extern const uint8_t dmg_esc_{s}[];')
    c = ['#include "dmg_data.h"', '/* generated by tools/gen_dmg_assets.py - do not edit (bank 0) */']
    c += arr('dmg_bank', [banks[s] for s in range(8)])
    c += arr('dmg_ntiles', [len(sc.tiles.list) for sc in screens])
    for n in ('chr', 'map'):
        c.append(f'const uint8_t *const dmg_{n}[8] = {{' + ','.join(f'dmg_{n}_{s}' for s in range(8)) + '};')
    c.append('const uint8_t *const dmg_esc[8] = {' + ','.join(f'dmg_esc_{s}' if s in esc else '0' for s in range(8)) + '};')
    c += arr('dmg_marker_chr', [b for t in marker for b in chr_bytes(t)])
    for old in OUT.glob('dmg_bank*.c'):
        old.unlink()
    (OUT / 'dmg_data.h').write_text('\n'.join(h) + '\n', newline='\n')
    (OUT / 'dmg_data.c').write_text('\n'.join(c) + '\n', newline='\n')
    for b, lines in files.items():
        (OUT / f'dmg_bank{b}.c').write_text('\n'.join(lines) + '\n', newline='\n')
    print('banks', banks, '-> wrote src/dmg/dmg_data.c/.h, dmg_bank%d..%d.c' % (FIRST_BANK, nbanks))
