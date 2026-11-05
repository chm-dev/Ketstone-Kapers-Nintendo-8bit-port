#!/usr/bin/env python3
"""GBC assets for the Keystone Kapers port (Game Boy Color colour path of the one GB ROM, build_gbc.ps1).
The ROM also carries the DMG shade data (tools/gen_dmg_assets.py, banks from GBC_ROM_BANKS up): re-run
gen_dmg_assets.py --emit after this script whenever the GBC bank count changes.

Backgrounds: the same 8 screen composites as tools/gen_bg.py (same crop 160x181 and cleanup, plus the
  baked minimap box erased: the GBC shows the minimap in the window HUD).  Per screen, 6 CGB BG palettes
  of 4 colours (15-bit) are fitted to the 8x8 tiles of the static image AND every animated state
  (escalator phases on screens 0/7, elevator car states on screen 4, rebuilt like tools/gen_dyn.py), so
  stripe white and car teal are covered.  Tiles are deduplicated with H/V flips (CGB attribute bits).
  Palettes 6 and 7 are the HUD's (minimap, text).  VRAM: screen tiles in bank 1 (ids 0..255),
  HUD/window tiles in bank 0 BG ids 0..127 ($9000), sprite tiles in bank 0 OBJ ids 0..127 ($8000).
Sprites: src/spr_data.c tiles/metasprites are used as they are (main_gbc.c remaps the NES props);
  OBJ palettes = the NES spr_palettes ids converted to RGB with gen_bg.py's NES table; 3 marker palettes.
HUD: 5x7 font of tools/gen_hud.py (colour 3 on colour 1 so the BG-priority bit hides sprites), hat,
  minimap (10x2 tiles cut from the Atari composite), 2x2 px marker sprite tile.
Sound: GB register values for the NES tables of src/sound_data.c (no runtime division):
  pulse/wave frequency x = 2048 - 1.17175*(t+1) (NES pulse t -> GB pulse, NES triangle t -> GB wave with
  a 32-step triangle: same formula), NES noise period index -> nearest NR43 (+ bit 3 for periodic mode).

Output: src/gbc/gbc_data.h, src/gbc/gbc_data.c (bank 0: tables, palettes, sound),
        src/gbc/gbc_bank<N>.c (ROM bank N data; build_gbc.ps1 compiles each with -Wf-bo<N>),
        assets/data/gbc_preview.png (Atari | GBC for the static screens and every animated state).
Usage: python -I tools/gen_gbc_assets.py [--emit]
Re-run with --emit after gen_assets.py --emit (spr_data.c) or gen_sound.py (sound_data.c): build_gbc.ps1
checks their fingerprint.  Also after any change of the screen composites / gen_bg.py cleanup.
"""
import argparse
import csv
import hashlib
import importlib.util
import itertools
import re
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SCR = ROOT / 'assets/atari/runtime/screens'
OUT = ROOT / 'src/gbc'
TW, TH = 20, 24
NPAL = 6                       # BG palettes per screen (6 = minimap, 7 = HUD text)
PAL_MAP, PAL_TXT = 6, 7
BANK_BYTES = 16000             # data per ROM bank (16384 minus a margin)

ap = argparse.ArgumentParser()
ap.add_argument('--emit', action='store_true')
args = ap.parse_args()

# ---------------------------------------------------------------- Atari images (gen_bg.py crop + clean)
SKY = (106, 124, 244)
BLACK = (0, 0, 0)
GREY = (131, 126, 133)         # street
SPECK = (148, 161, 255)
COPYCOLS = [                   # = tools/gen_bg.py COPYCOLS (baked objects)
    (1, 70, 82, 41, 52, 60), (2, 70, 82, 74, 84, 64), (2, 70, 82, 105, 116, 64), (2, 70, 82, 138, 148, 64)]
ELEV = (4, 72, 80, 57, 121, 24)
MAPBOX = (40, 120, 156, 170)   # baked minimap box: x 40..119, y 156..169


def pf_of(path):
    return np.asarray(Image.open(path).convert('RGB').crop((8, 23, 328, 204)).resize((160, 181), Image.NEAREST))


def clean(s, a):
    a = a.copy()
    for (cs, x0, x1, y0, y1, rx) in COPYCOLS:
        if cs == s:
            for y in range(y0, y1):
                a[y, x0:x1] = a[y, rx]
    if s == ELEV[0]:
        _, x0, x1, sy, dy, n = ELEV
        a[dy:dy + n, x0:x1] = a[sy:sy + n, x0:x1]
    a[0:18] = SKY
    a[173:181] = BLACK
    for y in range(160, 173):
        for x in range(1, 160):
            if tuple(a[y, x]) == SPECK:
                a[y, x] = a[y, x - 1]
    x0, x1, y0, y1 = MAPBOX     # GBC: minimap lives in the window HUD
    for y in range(y0, y1):
        a[y, x0:x1] = a[y, x0 - 1]
    return a


def composite(s):
    out = np.zeros((192, 160, 3), np.uint8)
    out[:181] = clean(s, pf_of(SCR / f'screen_{s}.png'))
    return out


def eq(a, c):
    return (a == np.array(c, np.uint8)).all(-1)


def shots(screen):
    rows = list(csv.DictReader(open(SCR / 'shots.csv')))
    return [(int(r['frame']), pf_of(SCR / f"shots/{int(r['frame']):04d}.png")) for r in rows if r['screen'] == str(screen)]


# ---------------------------------------------------------------- escalators (= tools/gen_dyn.py, AC88-ACFB)
B8DA = [0x6E, 0x6D, 0x6C, 0x6B]
B8DE = [0x72, 0x73, 0x74, 0x75]
B8E2 = [0x02, 0x01, 0x00, 0x03]
STRIPE = (205, 198, 210)
GREEN = (0, 95, 0)
DARK = (0, 18, 0)
ESC = {0: [89], 7: [57, 121]}


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


def colbk_mask(s):
    m = np.zeros((192, 160), bool)
    for _, a in shots(s):
        for y0 in ESC[s]:
            m[y0:y0 + 25, 40:110] |= eq(a[y0:y0 + 25, 40:110], STRIPE)
    return m


def esc_phase(s, base, k, colbk):
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


# ---------------------------------------------------------------- elevator (= tools/gen_dyn.py, AD0F-AD99)
CAR_X = 72
CAR_TX = CAR_X // 8
CAR_Y0 = [121, 89, 57]
open_t = pf_of(SCR / 'shots/0605.png')[121:146, CAR_X:CAR_X + 8].copy()


def car_img(base, f, state):
    a = base.copy()
    y0 = CAR_Y0[f]
    if state:
        a[y0:y0 + 24, CAR_X:CAR_X + 8] = open_t[:24]
        if state == 1:
            a[y0:y0 + 25, CAR_X:CAR_X + 2] = DARK
            a[y0:y0 + 25, CAR_X + 6:CAR_X + 8] = DARK
    return a


# ---------------------------------------------------------------- colour helpers
def rgb555(c):
    r, g, b = (min(31, (int(v) * 31 + 127) // 255) for v in c)
    return r | (g << 5) | (b << 10)


W = np.array([0.3, 0.59, 0.11])


def dist(a, b):
    return float(np.sqrt((((np.array(a, float) - np.array(b, float)) * W) ** 2).sum()))


def lum(c):
    return 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]


# ---------------------------------------------------------------- per-screen palette fit + tiles
def fit_palettes(hists, colours, npal):
    """hists: list of (count array over colours) per block occurrence group. Returns npal lists of colour idx."""
    NC = len(colours)
    D = np.array([[dist(colours[i], colours[j]) for j in range(NC)] for i in range(NC)])
    H = np.array(hists, float)                                  # (blocks, NC)
    sets = [set(np.nonzero(h)[0]) for h in H]
    pals = []
    for bi in sorted(range(len(H)), key=lambda i: -len(sets[i])):
        cs = sets[bi]
        if len(cs) > 4:
            continue
        best = None
        for pi, p in enumerate(pals):
            u = p | cs
            if len(u) <= 4 and (best is None or len(u) - len(p) < best[0]):
                best = (len(u) - len(p), pi)
        if best is not None:
            pals[best[1]] |= cs
        elif len(pals) < npal:
            pals.append(set(cs))
    while len(pals) < npal:
        pals.append({0})
    pals = [sorted(p) for p in pals]

    def cost(pal):                                              # per block
        return H @ D[:, pal].min(1)

    for _ in range(30):
        c = np.stack([cost(p) for p in pals])
        assign = c.argmin(0)
        new = []
        for pi in range(npal):
            agg = H[assign == pi].sum(0)
            cand = [int(i) for i in np.argsort(-agg) if agg[i] > 0]
            if not cand:
                new.append(pals[pi])
                continue
            if len(cand) <= 4:
                new.append(sorted(cand))
                continue
            cand = cand[:12]
            best = min(itertools.combinations(cand, 4), key=lambda comb: float(agg @ D[:, list(comb)].min(1)))
            new.append(sorted(best))
        if new == pals:
            break
        pals = new
    # local search (as tools/gen_bg.py): try every colour in every slot, keep improvements; random restarts
    def total(ps):
        return float(np.stack([cost(p) for p in ps]).min(0).sum())

    def polish(ps):
        ps = [list(p) for p in ps]
        cur = total(ps)
        improved = True
        while improved:
            improved = False
            for pi in range(npal):
                for k in range(4):
                    for col in range(NC):
                        if col in ps[pi]:
                            continue
                        old = ps[pi][k]
                        ps[pi][k] = col
                        v = total(ps)
                        if v < cur - 1e-9:
                            cur, improved = v, True
                        else:
                            ps[pi][k] = old
        return cur, ps

    pals = [p + [p[-1]] * (4 - len(p)) for p in pals]
    best = polish(pals)
    rng = np.random.default_rng(1)
    for _ in range(6):
        if best[0] == 0:
            break
        start = [list(rng.choice(NC, 4, replace=False)) for _ in range(npal)]
        r = polish(start)
        if r[0] < best[0]:
            best = r
    err, pals = best
    pals = [sorted(set(int(i) for i in p)) for p in pals]
    return pals, D, err


class Tiles:
    """dedup with flips; ids from first_id upward."""
    def __init__(self):
        self.list = []
        self.index = {}

    def add(self, t):
        for fl, v in ((0, t), (0x20, t[:, ::-1]), (0x40, t[::-1, :]), (0x60, t[::-1, ::-1])):
            k = v.tobytes()
            if k in self.index:
                return self.index[k], fl
        self.index[t.tobytes()] = len(self.list)
        self.list.append(t)
        return len(self.list) - 1, 0


def chr_bytes(t):
    out = []
    for y in range(8):
        out.append(sum(((int(t[y, x]) & 1) << (7 - x)) for x in range(8)))
        out.append(sum((((int(t[y, x]) >> 1) & 1) << (7 - x)) for x in range(8)))
    return out


def blocks_of(img):
    return {(tx, ty): img[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8] for ty in range(TH) for tx in range(TW)}


class Screen:
    def __init__(self, s, base, variants):
        """variants: dict name -> image (animated states); base = image whose map is uploaded."""
        self.s = s
        imgs = [base] + list(variants.values())
        colours = sorted({tuple(int(v) for v in p) for im in imgs for p in im.reshape(-1, 3)})
        cidx = {c: i for i, c in enumerate(colours)}
        self.colours = colours
        bb = blocks_of(base)
        groups = {}
        def add(blk):
            k = blk.tobytes()
            if k not in groups:
                ix = np.array([[cidx[tuple(int(v) for v in p)] for p in row] for row in blk])
                groups[k] = [ix, 0]
            groups[k][1] += 1
        for b in bb.values():
            add(b)
        for im in variants.values():
            for pos, b in blocks_of(im).items():
                if not (b == bb[pos]).all():
                    add(b)
        hist = [np.bincount(ix.ravel(), minlength=len(colours)) * 1 for ix, n in groups.values()]
        wts = [n for ix, n in groups.values()]
        pals, D, err = fit_palettes([h * w for h, w in zip(hist, wts)], colours, NPAL)
        pals = [sorted(p, key=lambda i: lum(colours[i])) for p in pals]
        pals = [p + [p[-1]] * (4 - len(p)) for p in pals]
        self.pals, self.D, self.err = pals, D, err
        self.cidx = cidx
        self.tiles = Tiles()
        self.base = self.quant(base)
        self.var = {k: self.quant(v) for k, v in variants.items()}

    def quant_block(self, blk):
        ix = np.array([[self.cidx[tuple(int(v) for v in p)] for p in row] for row in blk])
        best = None
        for pi, p in enumerate(self.pals):
            sub = self.D[ix][:, :, p]
            e = float(sub.min(-1).sum())
            if best is None or e < best[0]:
                best = (e, pi, sub.argmin(-1).astype(np.uint8))
        _, pi, q = best
        tid, fl = self.tiles.add(q)
        return tid, pi | fl | 0x08          # 0x08: VRAM bank 1

    def quant(self, img):
        return {pos: self.quant_block(b) for pos, b in blocks_of(img).items()}

    def render(self, q):
        pix = np.zeros((192, 160, 3), np.uint8)
        for (tx, ty), (tid, at) in q.items():
            t = self.tiles.list[tid]
            if at & 0x20:
                t = t[:, ::-1]
            if at & 0x40:
                t = t[::-1, :]
            cols = np.array([self.colours[i] for i in self.pals[at & 7]], np.uint8)
            pix[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8] = cols[t]
        return pix


previews = []
screens = []
for s in range(8):
    base = composite(s)
    variants = {}
    if s in (0, 7):
        colbk = colbk_mask(s)
        esc_base = base.copy()
        esc_base[colbk] = GREEN
        ph = [esc_phase(s, esc_base, k, colbk) for k in range(4)]
        base = ph[0]
        for k in range(1, 4):
            variants[f'ph{k}'] = ph[k]
    if s == 4:
        for f in range(3):
            for st in (1, 2):
                variants[f'f{f}s{st}'] = car_img(base, f, st)
    sc = Screen(s, base, variants)
    screens.append(sc)
    print(f'screen {s}: {len(sc.colours)} colours, palette error {sc.err:.0f}, {len(sc.tiles.list)} tiles')
    assert len(sc.tiles.list) <= 256, 'screen tiles exceed VRAM bank 1'
    previews.append((f's{s}', base, sc.render(sc.base)))
    for k, v in variants.items():
        if k in ('ph2', 'f0s2', 'f2s1'):
            q = dict(sc.base)
            q.update(sc.var[k])
            previews.append((f's{s} {k}', v, sc.render(q)))

# dynamic data
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
    v = [len(runs)]
    for tx, ty, w in runs:
        v += [tx, ty, w]
        for q in allq:
            v += [q[(tx + i, ty)][0] for i in range(w)] + [q[(tx + i, ty)][1] for i in range(w)]
    esc[s] = v
    print(f'screen {s}: escalator {len(dyn)} positions in {len(runs)} runs')
sc4 = screens[4]
elev = []                                 # [floor][state][4 tiles + 4 attrs]
for f in range(3):
    ty0 = CAR_Y0[f] // 8
    for st in range(3):
        q = sc4.base if st == 0 else sc4.var[f'f{f}s{st}']
        elev += [q[(CAR_TX, ty0 + i)][0] for i in range(4)] + [q[(CAR_TX, ty0 + i)][1] for i in range(4)]
    for st in (1, 2):                      # nothing outside the car column may change
        q = sc4.var[f'f{f}s{st}']
        bad = [p for p in q if q[p] != sc4.base[p] and not (p[0] == CAR_TX and ty0 <= p[1] < ty0 + 4)]
        assert not bad, f'elevator state changes tiles outside the car column: {bad}'

# ---------------------------------------------------------------- HUD (window) tiles
spec = importlib.util.spec_from_file_location('gen_hud', ROOT / 'tools/gen_hud.py')
gen_hud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen_hud)        # module level only reads files; main() is not run
G, ORDER = gen_hud.G, gen_hud.ORDER


def glyph(ch, fg=3, bg=1):
    t = np.full((8, 8), bg, np.uint8)
    for r, row in enumerate(G[ch]):
        for c, b in enumerate(row):
            if b == '1':
                t[r, c + 1] = fg
    return t


HAT = np.array([[int(ch) for ch in row] for row in      # colour 2 (hat) on colour 1 (black)
                ["11111111", "11122111", "11222211", "11222211", "12222221", "12222221", "22222222", "11111111"]],
               np.uint8)
hud_tiles = [glyph(ch) for ch in ORDER] + [HAT]
HT_HAT = len(hud_tiles) - 1
# minimap: Atari composite rows 155..170, x 40..119 (box 156..169); street grey and the speck -> dark
raw = pf_of(SCR / 'screen_0.png').copy()
mm = raw[155:171, 40:120].copy()
mm[eq(mm, SPECK)] = GREEN
mm[eq(mm, GREY)] = DARK
mcols = sorted({tuple(int(v) for v in p) for p in mm.reshape(-1, 3)}, key=lum)
assert len(mcols) <= 4, mcols
mcols += [mcols[-1]] * (4 - len(mcols))
HT_MAP = len(hud_tiles)
for ty in range(2):
    for tx in range(10):
        blk = mm[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8]
        hud_tiles.append(np.array([[mcols.index(tuple(int(v) for v in p)) for p in row] for row in blk], np.uint8))
HUD_PAL = {PAL_MAP: mcols, PAL_TXT: [BLACK, BLACK, (212, 136, 32), (236, 238, 236)]}
marker = np.zeros((8, 8), np.uint8)
marker[0:2, 0:2] = 1

# ---------------------------------------------------------------- sprites: OBJ palettes
NES = {int(i, 16): (int(r), int(g), int(b)) for i, r, g, b in re.findall(
    r'\((0x[0-9A-Fa-f]{2}),\s*\((\d+),\s*(\d+),\s*(\d+)\)\)', (ROOT / 'tools/gen_bg.py').read_text())}


def c_array(src, name):
    m = re.search(r'\b%s\[[^\]]*\]\s*=\s*\{(.*?)\};' % name, src, re.S)
    return [int(x, 0) for x in re.findall(r'0x[0-9A-Fa-f]+|\d+', m.group(1))]


spr_pal = c_array((ROOT / 'src/spr_data.c').read_text(), 'spr_palettes')
obj_pal = [rgb555(NES[c]) for c in spr_pal]
MARK_COL = [(236, 238, 236), (236, 60, 40), (240, 220, 0)]      # Kop white, thief red, car yellow
for c in MARK_COL:
    obj_pal += [0, rgb555(c), rgb555(c), rgb555(c)]

# ---------------------------------------------------------------- sound: GB register values
snd = (ROOT / 'src/sound_data.c').read_text()
# the GBC tables copy values/indices out of these two generated files: build_gbc.ps1 refuses stale data
FINGERPRINT = hashlib.sha1(b''.join((ROOT / f).read_bytes().replace(b'\r\n', b'\n')
                                    for f in ('src/spr_data.c', 'src/sound_data.c'))).hexdigest()[:16]
eff_start, eff_chan, eff_cfg = c_array(snd, 'snd_eff_start'), c_array(snd, 'snd_eff_chan'), c_array(snd, 'snd_eff_cfg')
st_dur, st_lo, st_hi = c_array(snd, 'snd_step_dur'), c_array(snd, 'snd_step_lo'), c_array(snd, 'snd_step_hi')
NOISE_NES = [4, 8, 16, 32, 64, 96, 128, 160, 202, 254, 380, 508, 762, 1016, 2034, 4068]


def gb_freq(t):
    return max(0, min(2047, 2048 - int(round(1.17175 * (t + 1)))))


def nr43(idx):
    f = 1789773.0 / NOISE_NES[idx]
    best = None
    for sh in range(14):
        for r in range(8):
            g = 524288.0 / (r if r else 0.5) / (2 ** (sh + 1))
            e = abs(np.log(g / f))
            if best is None or e < best[0]:
                best = (e, (sh << 4) | r)
    return best[1]


step_a = [0] * len(st_dur)
step_b = [0] * len(st_dur)
for e in range(1, len(eff_start)):
    i = eff_start[e]
    while i < len(st_dur) and st_dur[i] not in (0, 255):
        if eff_chan[e] == 0:                     # pulse: NR13 / NR14 bits 0-2
            x = gb_freq((st_hi[i] << 8) | st_lo[i])
            step_a[i], step_b[i] = x & 0xFF, x >> 8
        else:                                    # noise: NR43 (bit 3 = 7-bit LFSR for NES periodic mode)
            step_a[i] = nr43(st_lo[i] & 15) | (8 if eff_cfg[e] & 0x80 else 0)
        i += 1
bp_lo, bp_hi = c_array(snd, 'snd_bgm_p_lo'), c_array(snd, 'snd_bgm_p_hi')
bt_lo, bt_hi = c_array(snd, 'snd_bgm_t_lo'), c_array(snd, 'snd_bgm_t_hi')
bgm = []
for lo, hi in ((bp_lo, bp_hi), (bt_lo, bt_hi)):
    xs = [0 if h == 0xFF else gb_freq((h << 8) | l) for l, h in zip(lo, hi)]
    bgm.append(([x & 0xFF for x in xs], [x >> 8 for x in xs]))

# ---------------------------------------------------------------- preview
Wd = 160 * 2 + 8
pv = Image.new('RGB', (Wd * 3, 200 * ((len(previews) + 2) // 3) + 40), (40, 40, 40))
for i, (name, a, n) in enumerate(previews):
    x, y = (i % 3) * Wd, (i // 3) * 200
    pv.paste(Image.fromarray(a), (x, y))
    pv.paste(Image.fromarray(n), (x + 164, y))
hud = np.zeros((16, 160, 3), np.uint8)
for i in range(20):
    t = hud_tiles[HT_MAP + i]
    hud[(i // 10) * 8:(i // 10) * 8 + 8, (i % 10) * 8:(i % 10) * 8 + 8] = np.array(mcols, np.uint8)[t]
for i, ch in enumerate('123400 T50'):
    t = hud_tiles[ORDER.index(ch)]
    hud[0:8, 80 + i * 8:88 + i * 8] = np.array(HUD_PAL[PAL_TXT], np.uint8)[t]
pv.paste(Image.fromarray(hud).resize((320, 32), Image.NEAREST), (0, pv.height - 36))
pv.save(ROOT / 'assets/data/gbc_preview.png')
print('wrote assets/data/gbc_preview.png (Atari | GBC per state)')

# ---------------------------------------------------------------- emit
if args.emit:
    OUT.mkdir(exist_ok=True)

    def arr(name, vals, per=16, typ='uint8_t', static=False):
        out = [f'{"static " if static else ""}const {typ} {name}[] = {{']
        for i in range(0, len(vals), per):
            out.append('  ' + ','.join(str(v) for v in vals[i:i + per]) + ',')
        return out + ['};']

    # bank assignment
    banks = {}
    bank, used = 1, 0
    blobs = []
    hud_bytes = [b for t in hud_tiles for b in chr_bytes(t)]
    items = [('hud', len(hud_bytes))] + [(s, len(screens[s].tiles.list) * 16 + 2 * TW * TH + 64 + 200) for s in range(8)]
    for key, n in items:
        if used + n > BANK_BYTES:
            bank, used = bank + 1, 0
        banks[key] = bank
        used += n
    nbanks = bank
    files = {b: ['#include "gbc_data.h"', '/* generated by tools/gen_gbc_assets.py - do not edit */']
             for b in range(1, nbanks + 1)}
    files[banks['hud']] += arr('gbc_hud_chr', hud_bytes)
    for s, sc in enumerate(screens):
        f = files[banks[s]]
        f += arr(f'gbc_chr_{s}', [b for t in sc.tiles.list for b in chr_bytes(t)])
        f += arr(f'gbc_map_{s}', [sc.base[(tx, ty)][0] for ty in range(TH) for tx in range(TW)], TW)
        f += arr(f'gbc_attr_{s}', [sc.base[(tx, ty)][1] for ty in range(TH) for tx in range(TW)], TW)
        pal = []
        for p in sc.pals:
            pal += [rgb555(sc.colours[i]) for i in p]
        f += arr(f'gbc_pal_{s}', pal, 8, 'uint16_t')
        if s in esc:
            f += arr(f'gbc_esc_{s}', esc[s])
    files[banks[4]] += arr('gbc_elev', elev, 8)

    h = ['#ifndef GBC_DATA_H', '#define GBC_DATA_H', '#include <stdint.h>',
         '/* generated by tools/gen_gbc_assets.py - do not edit.  Banked arrays: SWITCH_ROM(gbc_bank[s]) first. */',
         '/* CGB screen/HUD/palette data of the one GB ROM (+ sound tables, both machines); the DMG shades are src/dmg/dmg_data.h */',
         f'#define GBC_BG_W {TW}u', f'#define GBC_BG_H {TH}u',
         f'#define GBC_NPAL {NPAL}u            /* BG palettes per screen (0..{NPAL - 1}) */',
         f'#define GBC_PAL_MAP {PAL_MAP}u        /* minimap (window) */',
         f'#define GBC_PAL_TXT {PAL_TXT}u        /* HUD text (window) */',
         f'#define GBC_ROM_BANKS {nbanks + 1}u      /* banks 0..{nbanks} used (the DMG data follows) */',
         f'#define GBC_SRC_FINGERPRINT "{FINGERPRINT}"  /* sha1 of src/spr_data.c + src/sound_data.c used (build_gbc.ps1 checks it) */',
         '/* screen s: tiles go to VRAM bank 1 ids 0.., map/attr = 20x24 (attr has bit 3 = bank 1, flips, palette) */',
         'extern const uint8_t gbc_bank[8];',
         'extern const uint8_t gbc_ntiles[8];',
         'extern const uint8_t *const gbc_chr[8];',
         'extern const uint8_t *const gbc_map[8];',
         'extern const uint8_t *const gbc_attr[8];',
         'extern const uint16_t *const gbc_pal[8];      /* GBC_NPAL x 4 colours */',
         '/* escalators (screens 0, 7): count, then per run tx, ty, w, and per phase 0..3: w tile ids, w attrs */',
         'extern const uint8_t *const gbc_esc[8];        /* 0 = none */',
         f'#define GBC_ELEV_TX {CAR_TX}u',
         'extern const uint8_t gbc_elev_ty[3];',
         'extern const uint8_t gbc_elev[];               /* [floor][state 0 closed,1 moving,2 open][4 ids + 4 attrs] (bank gbc_bank[4]) */',
         '/* HUD (window): VRAM bank 0 BG ids 0.., font order "0-9A-Z :-!" */',
         f'#define GBC_HUD_BANK {banks["hud"]}u',
         f'#define GBC_HUD_NTILES {len(hud_tiles)}u',
         '#define GBC_HT_FONT 0u',
         '#define GBC_HT_SPACE 36u',
         f'#define GBC_HT_HAT {HT_HAT}u',
         f'#define GBC_HT_MAP {HT_MAP}u          /* 10x2 minimap tiles, row-major */',
         'extern const uint8_t gbc_hud_chr[];',
         'extern const uint16_t gbc_hud_pal[8];        /* BG palettes GBC_PAL_MAP, GBC_PAL_TXT */',
         'extern const uint8_t gbc_marker_chr[16];     /* 2x2 px marker, colour 1 */',
         'extern const uint16_t gbc_obj_pal[28];       /* OBJ palettes 0-3 sprites (NES ids -> RGB), 4-6 markers */',
         '/* sound: GB values for the src/sound_data.c steps (pulse: NR13 + NR14 bits; noise: NR43) */',
         f'extern const uint8_t gbc_snd_a[{len(step_a)}], gbc_snd_b[{len(step_b)}];',
         'extern const uint8_t gbc_bgm_p_lo[100], gbc_bgm_p_hi[100];   /* pulse 2 */',
         'extern const uint8_t gbc_bgm_w_lo[100], gbc_bgm_w_hi[100];   /* wave (NES triangle) */',
         '#endif']
    for s in range(8):
        h.insert(-1, f'extern const uint8_t gbc_chr_{s}[], gbc_map_{s}[], gbc_attr_{s}[];')
        h.insert(-1, f'extern const uint16_t gbc_pal_{s}[];')
    for s in esc:
        h.insert(-1, f'extern const uint8_t gbc_esc_{s}[];')
    c = ['#include "gbc_data.h"', '/* generated by tools/gen_gbc_assets.py - do not edit (bank 0) */']
    c += arr('gbc_bank', [banks[s] for s in range(8)])
    c += arr('gbc_ntiles', [len(sc.tiles.list) for sc in screens])
    for n in ('chr', 'map', 'attr'):
        c.append(f'const uint8_t *const gbc_{n}[8] = {{' + ','.join(f'gbc_{n}_{s}' for s in range(8)) + '};')
    c.append('const uint16_t *const gbc_pal[8] = {' + ','.join(f'gbc_pal_{s}' for s in range(8)) + '};')
    c.append('const uint8_t *const gbc_esc[8] = {' + ','.join(f'gbc_esc_{s}' if s in esc else '0' for s in range(8)) + '};')
    c += arr('gbc_elev_ty', [y // 8 for y in CAR_Y0])
    c += arr('gbc_hud_pal', [rgb555(x) for x in HUD_PAL[PAL_MAP] + HUD_PAL[PAL_TXT]], 8, 'uint16_t')
    c += arr('gbc_marker_chr', chr_bytes(marker))
    c += arr('gbc_obj_pal', obj_pal, 4, 'uint16_t')
    c += arr('gbc_snd_a', step_a) + arr('gbc_snd_b', step_b)
    c += arr('gbc_bgm_p_lo', bgm[0][0]) + arr('gbc_bgm_p_hi', bgm[0][1])
    c += arr('gbc_bgm_w_lo', bgm[1][0]) + arr('gbc_bgm_w_hi', bgm[1][1])
    for old in OUT.glob('gbc_bank*.c'):
        old.unlink()
    (OUT / 'gbc_data.h').write_text('\n'.join(h) + '\n', newline='\n')
    (OUT / 'gbc_data.c').write_text('\n'.join(c) + '\n', newline='\n')
    for b, lines in files.items():
        (OUT / f'gbc_bank{b}.c').write_text('\n'.join(lines) + '\n', newline='\n')
    print('banks', banks, '-> wrote src/gbc/gbc_data.c/.h, gbc_bank1..%d.c' % nbanks)
