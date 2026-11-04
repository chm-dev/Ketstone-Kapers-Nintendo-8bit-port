#!/usr/bin/env python3
"""Decode the Atari display list in a 64 KiB RAM dump and render the bitmap rows.

Handles ANTIC modes 6/C/E-style lines enough to eyeball Keystone Kapers: mode C = 160x1 two-colour
bitmap, 20 bytes/scanline (ANTIC mode 12).  Output: <out>.png (x2 wide, monochrome) and a DL listing.

Usage: python tools/render_dl.py RAM.bin [--dl 0x0A00] [--out build/dl.png]
"""
import argparse
from pathlib import Path

BYTES = {0x6: 20, 0x7: 20, 0xC: 20, 0xD: 40, 0xE: 40, 0xF: 40, 0x2: 40, 0x3: 40, 0x4: 40, 0x5: 40}
LINES = {0x6: 8, 0x7: 16, 0xC: 1, 0xD: 2, 0xE: 1, 0xF: 1, 0x2: 8, 0x3: 10, 0x4: 8, 0x5: 16}


def decode(ram, dl):
    i, rows, mem, listing = dl, [], 0, []
    while i < dl + 0x400:
        b = ram[i]; m = b & 15
        if m == 0:
            n = ((b >> 4) & 7) + 1
            listing.append(f'{i:04X}: blank {n}'); rows.append(('blank', n)); i += 1; continue
        if m == 1:
            tgt = ram[i + 1] | ram[i + 2] << 8
            listing.append(f'{i:04X}: {"JVB" if b & 0x40 else "JMP"} {tgt:04X}')
            if b & 0x40: break
            i = tgt; continue
        if b & 0x40:
            mem = ram[i + 1] | ram[i + 2] << 8; ln = 3
        else:
            ln = 1
        flags = ('DLI ' if b & 0x80 else '') + ('LMS ' if b & 0x40 else '') + ('HS ' if b & 0x10 else '')
        listing.append(f'{i:04X}: mode {m:X} {flags}mem={mem:04X}')
        rows.append(('line', m, mem, bool(b & 0x80), bool(b & 0x10)))
        mem += BYTES.get(m, 40); i += ln
    return rows, listing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('ram')
    ap.add_argument('--dl', type=lambda x: int(x, 0), default=0x0A00)
    ap.add_argument('--out', default='build/dl.png')
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()
    ram = Path(a.ram).read_bytes()
    rows, listing = decode(ram, a.dl)
    if a.list:
        print('\n'.join(listing))
    from PIL import Image
    W = 160
    img_rows = []
    for r in rows:
        if r[0] == 'blank':
            img_rows += [[0] * W] * r[1]; continue
        _, m, mem = r[:3]
        if m == 0xC:
            bits = []
            for k in range(20):
                v = ram[(mem + k) & 0xFFFF]
                bits += [(v >> s) & 1 for s in range(7, -1, -1)]
            img_rows.append(bits)
        else:
            img_rows += [[0] * W] * LINES.get(m, 8)
    im = Image.new('L', (W, len(img_rows)))
    im.putdata([255 if p else 0 for row in img_rows for p in row])
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    im.resize((W * 3, len(img_rows) * 3), Image.NEAREST).save(a.out)
    print(f'{len(rows)} DL entries, {len(img_rows)} scanlines -> {a.out}')


if __name__ == '__main__':
    main()
