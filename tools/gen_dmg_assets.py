#!/usr/bin/env python3
"""DMG (original Game Boy, 4 grey shades) assets for the Keystone Kapers port (build_dmg.ps1).

Reuses the Atari image pipeline of tools/gen_gbc_assets.py (its source up to the preview section is
exec'd: same crop 160x181, object cleanup, minimap box erased, escalator phases, elevator car states).
Backgrounds: every pixel -> one of 4 shades by the luma of its Atari colour (SHADE_LIMITS below), tiles
  deduplicated per screen WITHOUT flips (a DMG BG tile has no flip bits), animated states included so
  every tile of every state is in VRAM.  Map ids = DMG_TILE_BASE + tile (HUD tiles come first).
VRAM budget (384 tiles, one bank): OBJ ids 0..127 at $8000 = sprites (41 tiles) + marker tiles;
  BG ids 0..127 at $9000 and 128..255 at $8800 (GBDK default BG8800 mode) = HUD tiles (ids 0..60) +
  the current screen's tiles (ids 61..255).  OBJ ids 128..255 share $8800 with the BG: unused.
Sprites: src/spr_data.c tile data baked per NES palette (colour slot -> shade by luma rank,
  SPR_SHADES), so one OBP0 serves all frames; OBP1 = identity for the minimap car marker.
HUD: 5x7 font white on black (BGP identity: idx 0 white .. idx 3 black), hat, minimap cut from the
  Atari composite, 2 marker tiles.  Sound: shared with the GBC (src/gbc/gbc_data.c, GB_DMG).
Output: src/dmg/dmg_data.h, dmg_data.c (bank 0 tables), dmg_bank<N>.c, assets/data/dmg_preview.png.
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
# shade 0 white .. 3 black (BGP identity).  luma < limit[i] -> shade 3 - i.
#   black / dark greens (<45) -> 3, floors + skyline (56, 61) -> 2, olive lines + street + grey (<130) -> 1,
#   sky, sunset, stripe white, orange (>=130) -> 0
SHADE_LIMITS = (45, 80, 130)
SPR_SHADES = (3, 1, 0)        # sprite colour slots by ascending luma -> shade (black, light grey, white)


def shade_of(c):
    l = lum(c)
    for i, lim in enumerate(SHADE_LIMITS):
        if l < lim:
            return 3 - i
    return 0


_cache = {}


def shade_img(img):
    flat = img.reshape(-1, 3)
    out = np.empty(len(flat), np.uint8)
    for i, p in enumerate(map(tuple, flat.tolist())):
        v = _cache.get(p)
        if v is None:
            v = _cache[p] = shade_of(p)
        out[i] = v
    return out.reshape(img.shape[:2])


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
    def __init__(self, base, variants):
        self.tiles = Tiles()
        self.base = {p: self.tiles.add(b) for p, b in blocks(shade_img(base)).items()}
        self.var = {k: {p: self.tiles.add(b) for p, b in blocks(shade_img(v)).items()} for k, v in variants.items()}

    def render(self, q):
        pix = np.zeros((192, 160), np.uint8)
        for (tx, ty), tid in q.items():
            pix[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8] = self.tiles.list[tid]
        return pix


screens, previews = [], []
for s in range(8):
    base = composite(s)
    variants = {}
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
    sc = Scr(base, variants)
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
msh = shade_img(mm)
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
tile_pal = {}
for m in re.finditer(r'ms_\w+\[\] = \{(.*?)\};', src):
    for t, p in re.findall(r'METASPR_ITEM\(-?\d+,-?\d+,(\d+),(0x[0-9A-Fa-f]+)\)', m.group(1)):
        pal = int(p, 16) & 3
        assert tile_pal.setdefault(int(t), pal) == pal, f'sprite tile {t} used with two palettes'
assert set(tile_pal) == set(range(NT)), set(range(NT)) - set(tile_pal)
spr_pal = c_array(src, 'spr_palettes')
slot_shade = {}                    # (palette, colour slot 1..3) -> shade
for p in range(4):
    cols = [(k, lum(NES[spr_pal[p * 4 + k]])) for k in (1, 2, 3)]
    for rank, (k, _) in enumerate(sorted(cols, key=lambda kv: kv[1])):
        slot_shade[(p, k)] = SPR_SHADES[rank]
OBP0_SHADE = {1: 0, 2: 1, 3: 3}    # OBP0 idx -> shade (idx 0 transparent)
IDX_OF = {v: k for k, v in OBP0_SHADE.items()}
assert sorted(OBP0_SHADE.values()) == sorted(SPR_SHADES)
spr_out = []
for t, a in enumerate(spr_tiles):
    b = a.copy()
    for k in (1, 2, 3):
        b[a == k] = IDX_OF[slot_shade[(tile_pal[t], k)]]
    spr_out.append(b)
OBP0 = sum(OBP0_SHADE[k] << (2 * k) for k in (1, 2, 3))
OBP1 = 0xE4
BGP = 0xE4
marker = [np.zeros((8, 8), np.uint8), np.zeros((8, 8), np.uint8)]
marker[0][0:2, 0:2] = 1                  # OBP0 idx 1 = white (Kop) / OBP1 idx 1 = light grey (car)
marker[1][0:2, 0:2] = 3                  # idx 3 = black in both (thief)
print('sprite tiles', NT, 'marker tiles 2; OBP0', hex(OBP0), 'slot shades', slot_shade)
bud = {'BG ids': TILE_BASE + mx, 'OBJ ids': NT + 2}
print('VRAM budget: BG ids used up to %d of 256 (HUD %d + worst screen %d), OBJ %d of 128, %d of 384 tiles in use' % (
    bud['BG ids'], TILE_BASE, mx, bud['OBJ ids'], bud['BG ids'] + bud['OBJ ids']))

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

# ---------------------------------------------------------------- emit
if args.emit:
    OUT.mkdir(exist_ok=True)

    def arr(name, vals, per=16, typ='uint8_t'):
        out = [f'const {typ} {name}[] = {{']
        for i in range(0, len(vals), per):
            out.append('  ' + ','.join(str(v) for v in vals[i:i + per]) + ',')
        return out + ['};']

    hud_bytes = [b for t in hud for b in chr_bytes(t)]
    spr_bytes = [b for t in spr_out for b in chr_bytes(t)]
    banks, bank, used = {}, 1, 0
    items = [('hud', len(hud_bytes) + len(spr_bytes))] + [(s, len(screens[s].tiles.list) * 16 + TW * TH + 64 + 200) for s in range(8)]
    for key, n in items:
        if used + n > BANK_BYTES:
            bank, used = bank + 1, 0
        banks[key] = bank
        used += n
    nbanks = bank
    files = {b: ['#include "dmg_data.h"', '/* generated by tools/gen_dmg_assets.py - do not edit */']
             for b in range(1, nbanks + 1)}
    files[banks['hud']] += arr('gbc_hud_chr', hud_bytes) + arr('dmg_spr_chr', spr_bytes)
    for s, sc in enumerate(screens):
        f = files[banks[s]]
        f += arr(f'gbc_chr_{s}', [b for t in sc.tiles.list for b in chr_bytes(t)])
        f += arr(f'gbc_map_{s}', [TILE_BASE + sc.base[(tx, ty)] for ty in range(TH) for tx in range(TW)], TW)
        if s in esc:
            runs, allq = esc[s]
            v = [len(runs)]
            for tx, ty, w in runs:
                v += [tx, ty, w]
                for q in allq:
                    v += [TILE_BASE + q[(tx + i, ty)] for i in range(w)]
            f += arr(f'gbc_esc_{s}', v)
    files[banks[4]] += arr('gbc_elev', [TILE_BASE + t for st in elev for t in st], 4)

    h = ['#ifndef DMG_DATA_H', '#define DMG_DATA_H', '#include <stdint.h>',
         '/* generated by tools/gen_dmg_assets.py - do not edit.  Same symbol names as src/gbc/gbc_data.h (GB_DMG hides those).',
         ' * Banked arrays: SWITCH_ROM(gbc_bank[s]) first.  Tile ids in the maps are final (HUD ids 0..%d, screen tiles from DMG_TILE_BASE). */' % (TILE_BASE - 1),
         f'#define GBC_BG_W {TW}u', f'#define GBC_BG_H {TH}u',
         f'#define DMG_ROM_BANKS {nbanks + 1}u      /* banks 0..{nbanks} used */',
         f'#define DMG_SRC_FINGERPRINT "{FINGERPRINT}"  /* sha1 of src/spr_data.c (build_dmg.ps1 checks it) */',
         f'#define DMG_TILE_BASE {TILE_BASE}u     /* first BG id of a screen\'s tiles */',
         f'#define DMG_BGP {BGP}u',
         f'#define DMG_OBP0 {OBP0}u               /* sprites: idx 1 white, 2 light grey, 3 black */',
         f'#define DMG_OBP1 {OBP1}u',
         'extern const uint8_t gbc_bank[8];',
         'extern const uint8_t gbc_ntiles[8];',
         'extern const uint8_t *const gbc_chr[8];',
         'extern const uint8_t *const gbc_map[8];',
         '/* escalators (screens 0, 7): count, then per run tx, ty, w, and per phase 0..3: w tile ids */',
         'extern const uint8_t *const gbc_esc[8];        /* 0 = none */',
         f'#define GBC_ELEV_TX {CAR_TX}u',
         'extern const uint8_t gbc_elev_ty[3];',
         'extern const uint8_t gbc_elev[];               /* [floor][state 0 closed,1 moving,2 open][4 ids] (bank gbc_bank[4]) */',
         f'#define GBC_HUD_BANK {banks["hud"]}u',
         f'#define GBC_HUD_NTILES {len(hud)}u',
         '#define GBC_HT_FONT 0u', '#define GBC_HT_SPACE 36u',
         f'#define GBC_HT_HAT {HT_HAT}u', f'#define GBC_HT_MAP {HT_MAP}u',
         '#define DMG_MARK_TILE_A 0x7Eu             /* OBJ ids: marker idx 1 (Kop white, car light grey) */',
         '#define DMG_MARK_TILE_B 0x7Fu             /* marker idx 3 (thief black) */',
         'extern const uint8_t gbc_hud_chr[];      /* bank GBC_HUD_BANK */',
         f'extern const uint8_t dmg_spr_chr[{NT * 16}];  /* bank GBC_HUD_BANK: spr_data.c tiles baked to OBP0 idx */',
         'extern const uint8_t gbc_marker_chr[32];',
         '#endif']
    for s in range(8):
        h.insert(-1, f'extern const uint8_t gbc_chr_{s}[], gbc_map_{s}[];')
    for s in esc:
        h.insert(-1, f'extern const uint8_t gbc_esc_{s}[];')
    c = ['#include "dmg_data.h"', '/* generated by tools/gen_dmg_assets.py - do not edit (bank 0) */']
    c += arr('gbc_bank', [banks[s] for s in range(8)])
    c += arr('gbc_ntiles', [len(sc.tiles.list) for sc in screens])
    for n in ('chr', 'map'):
        c.append(f'const uint8_t *const gbc_{n}[8] = {{' + ','.join(f'gbc_{n}_{s}' for s in range(8)) + '};')
    c.append('const uint8_t *const gbc_esc[8] = {' + ','.join(f'gbc_esc_{s}' if s in esc else '0' for s in range(8)) + '};')
    c += arr('gbc_elev_ty', [y // 8 for y in CAR_Y0])
    c += arr('gbc_marker_chr', [b for t in marker for b in chr_bytes(t)])
    for old in OUT.glob('dmg_bank*.c'):
        old.unlink()
    (OUT / 'dmg_data.h').write_text('\n'.join(h) + '\n', newline='\n')
    (OUT / 'dmg_data.c').write_text('\n'.join(c) + '\n', newline='\n')
    for b, lines in files.items():
        (OUT / f'dmg_bank{b}.c').write_text('\n'.join(lines) + '\n', newline='\n')
    print('banks', banks, '-> wrote src/dmg/dmg_data.c/.h, dmg_bank1..%d.c' % nbanks)
