#!/usr/bin/env python3
"""gen_hud.py - HUD font, hat and minimap tiles -> src/hud_data.c / hud_data.h (banked const data).

Run from the repo root:  python -I tools/gen_hud.py
Colours are not hard-coded: the script reads the palettes that tools/gen_bg.py emitted (src/bg_data*.c,
tools/gen_bg.py's NES colour table) and the sprite palettes (src/spr_data.c), so re-run it after every
gen_bg.py / gen_assets.py --emit.  Roles: MARGIN palette = the BG palette holding the darkest colour (black
text background, minimap and title text, attribute of the pillarbox margins); SKY palette = the palette of the
top-left playfield cell (sky strip: darkest colour of that palette on the sky colour).
Tile layout (ids = HUD_T0 + index, GB-interleaved 2bpp as set_bkg_data() wants on NES too):
  0..39   font, light (colour 1) on black   - title/band text
  40..79  font, black (colour 3) on sky (colour 1) - the HUD strip in the sky band
  80      hat (Kop's spare lives)
  81      solid black (pillarbox margin)
Font order: '0'-'9' = 0-9, 'A'-'Z' = 10-35, ' ' = 36, ':' = 37, '-' = 38, '!' = 39.
Sprite tiles (hud_spr, upload at HUD_SPR_T0): 2x4 px minimap markers (Kop, thief, elevator car).
The 5x7 font is an original default (the Atari font only exists as a screenshot of chunky mode-C glyphs).
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

G = {
    '0': ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    '1': ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    '2': ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    '3': ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    '4': ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    '5': ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    '6': ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    '7': ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    '8': ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    '9': ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    'A': ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    'B': ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    'C': ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    'D': ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    'E': ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    'F': ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    'G': ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
    'H': ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    'I': ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    'J': ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    'K': ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    'L': ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    'M': ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    'N': ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    'O': ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    'P': ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    'Q': ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    'R': ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    'S': ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    'T': ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    'U': ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    'V': ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    'W': ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    'X': ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    'Y': ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    'Z': ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    ' ': ["00000"] * 7,
    ':': ["00000", "00100", "00100", "00000", "00100", "00100", "00000"],
    '-': ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    '!': ["00100", "00100", "00100", "00100", "00100", "00000", "00100"],
}
ORDER = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ :-!"
assert len(ORDER) == 40


import re


def read(p):
    return open(os.path.join(ROOT, p)).read()


def c_array(src, name):
    m = re.search(r'\b%s\[\d*\]\s*=\s*\{(.*?)\};' % name, src, re.S)
    return [int(x, 0) for x in re.findall(r'0x[0-9A-Fa-f]+|\d+', m.group(1))]


# NES colour id -> luma from gen_bg.py's table
RGB = {int(i, 16): tuple(int(v) for v in (r, g, b))
       for i, r, g, b in re.findall(r'\((0x[0-9A-Fa-f]{2}),\s*\((\d+),\s*(\d+),\s*(\d+)\)\)', read('tools/gen_bg.py'))}


def luma(i):
    r, g, b = RGB.get(i, (128, 128, 128))
    return 0.3 * r + 0.59 * g + 0.11 * b


bgsrc = read('src/bg_data.c')
BGPAL = c_array(bgsrc, 'bg_pal')
asrc = read('src/bg_data_a.c')
MAP0 = c_array(asrc, 'bg_map_0')
CHR0 = c_array(asrc, 'bg_chr_0')
ATTR0 = c_array(asrc, 'bg_attr_0')

# margin: darkest colour (index 1..3) of any palette
cands = [(luma(BGPAL[p * 4 + c]), p, c) for p in range(4) for c in (1, 2, 3)]
_, MP, BK = min(cands)
rest = sorted((luma(BGPAL[MP * 4 + c]), c) for c in (1, 2, 3) if c != BK)
LINE, FGL = rest[0][1], rest[1][1]       # minimap floor lines = dimmer, text / escalator ticks = brighter
# sky: palette of the top-left cell, colour of the top-left pixel of the top-left tile
SP = ATTR0[0]
t0 = MAP0[0]
SKYC = ((CHR0[t0 * 16] >> 7) & 1) | (((CHR0[t0 * 16 + 1] >> 7) & 1) << 1)
FGS = min((luma(BGPAL[SP * 4 + c]), c) for c in (1, 2, 3) if c != SKYC)[1]
print('margin pal', MP, 'black idx', BK, 'text idx', FGL, 'line idx', LINE, '| sky pal', SP, 'sky idx', SKYC, 'text idx', FGS)

# sprite markers: pick palette entries by colour id from src/spr_data.c
SPRPAL = c_array(read('src/spr_data.c'), 'spr_palettes')


def find_spr(wanted, fallback):
    for w in wanted:
        for p in range(4):
            for c in (1, 2, 3):
                if SPRPAL[p * 4 + c] == w:
                    return p, c
    return fallback


MK = [find_spr([0x30, 0x20, 0x38, 0x10, 0x3D], (3, 3)),      # Kop: white
      find_spr([0x16, 0x15, 0x06, 0x26, 0x17], (2, 2)),      # thief: red
      find_spr([0x28, 0x27, 0x38, 0x18], (3, 2))]            # elevator car: yellow


def encode(pix):
    """pix[8][8] colours 0-3 -> 16 bytes GB-interleaved (lo, hi per row)."""
    out = []
    for r in range(8):
        lo = hi = 0
        for c in range(8):
            v = pix[r][c]
            lo |= (v & 1) << (7 - c)
            hi |= ((v >> 1) & 1) << (7 - c)
        out += [lo, hi]
    return out


def glyph_tile(ch, fg, bg):
    pix = [[bg] * 8 for _ in range(8)]
    for r, row in enumerate(G[ch]):
        for c, b in enumerate(row):
            if b == '1':
                pix[r][c + 1] = fg
    return encode(pix)


def grid(rows, fg, bg):
    return [[fg if ch == '3' else bg for ch in row] for row in rows]


HAT = grid(["11111111", "11133111", "11333311", "11333311", "13333331", "13333331", "33333333", "11111111"], FGS, SKYC)


def marker(colour):
    pix = [[0] * 8 for _ in range(8)]
    for y in range(2):
        for x in range(2):
            pix[y][x] = colour
    return encode(pix)


def main():
    tiles = []
    for ch in ORDER:
        tiles += glyph_tile(ch, FGL, BK)
    for ch in ORDER:
        tiles += glyph_tile(ch, FGS, SKYC)
    tiles += encode(HAT)
    tiles += encode([[BK] * 8 for _ in range(8)])      # HT_BLACK: pillarbox margin
    n = len(tiles) // 16
    spr = []
    for p, c in MK:
        spr += marker(c)

    def arr(name, data):
        s = "const uint8_t %s[] = {\n" % name
        for i in range(0, len(data), 16):
            s += "  " + ",".join(str(b) for b in data[i:i + 16]) + ",\n"
        return s + "};\n"

    with open(os.path.join(ROOT, "src", "hud_data.c"), "w", newline="\n") as f:
        f.write('#include "hud_data.h"\n/* generated by tools/gen_hud.py - do not edit */\n')
        f.write(arr("hud_tiles", tiles))
        f.write(arr("hud_spr", spr))
    with open(os.path.join(ROOT, "src", "hud_data.h"), "w", newline="\n") as f:
        f.write("""#ifndef HUD_DATA_H
#define HUD_DATA_H
#include <stdint.h>
/* generated by tools/gen_hud.py - do not edit (re-run after gen_bg.py / gen_assets.py --emit) */
#define HUD_BANK 1u            /* PRG bank of hud_data.c (build.ps1 -Wf-bo1): SWITCH_ROM(HUD_BANK) before reading */
#define HUD_T0 0xA0u           /* first BG tile id (bg_ntiles must stay below it) */
#define HUD_NTILES %du
#define HT_FONT_L HUD_T0                   /* 40 glyphs, bright on black */
#define HT_FONT_S (HUD_T0 + 40u)           /* 40 glyphs, dark on sky */
#define HT_HAT    (HUD_T0 + 80u)
#define HT_BLACK  (HUD_T0 + 81u)           /* solid black: pillarbox margin */
#define HUD_MARGIN_PAL %du                 /* BG palette whose colour %d is black: margins, band */
#define HUD_SKY_PAL %du                    /* BG palette of the sky strip (sky = colour %d) */
#define HUD_SPR_T0 0x80u       /* first sprite tile id: Kop, thief, elevator markers */
#define HUD_NSPR 3u
#define HUD_SPR_PROP0 %du      /* OAM palette of each marker */
#define HUD_SPR_PROP1 %du
#define HUD_SPR_PROP2 %du
extern const uint8_t hud_tiles[HUD_NTILES * 16u];
extern const uint8_t hud_spr[HUD_NSPR * 16u];
#endif
""" % (n, MP, BK, SP, SKYC, MK[0][0], MK[1][0], MK[2][0]))
    print("hud tiles", n, "bytes", len(tiles))


if __name__ == "__main__":
    main()