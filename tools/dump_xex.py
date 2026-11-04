#!/usr/bin/env python3
"""Parse an Atari 8-bit XEX and list / dump its load segments.

Keystone Kapers xex is a multi-stage loader: several 8 KiB chunks loaded at
$2000-$3FFF (each followed by a 1-byte write to $D65F) and a final cartridge-
like image at $9F80-$BFFF. This tool prints every segment and writes each one
to assets/atari/segments/ so they can be inspected individually.

Usage: python tools/dump_xex.py [--xex xex/Keystone_Kapers.xex] [--out assets/atari/segments]
"""
import argparse, hashlib, struct
from pathlib import Path


def read_segments(d):
    i, segs = 0, []
    while i < len(d):
        s, e = struct.unpack_from('<HH', d, i)
        if s == 0xFFFF:
            i += 2
            continue
        i += 4
        # a header may be preceded by an extra FFFF; handled above
        if s == 0xFFFF:
            continue
        segs.append(dict(start=s, end=e, off=i, data=d[i:i + e - s + 1]))
        i += e - s + 1
    return segs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--xex', default='xex/Keystone_Kapers.xex')
    ap.add_argument('--out', default='assets/atari/segments')
    a = ap.parse_args()
    d = Path(a.xex).read_bytes()
    print('xex sha256', hashlib.sha256(d).hexdigest(), len(d), 'bytes')
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for n, s in enumerate(read_segments(d)):
        name = f"seg{n:02d}_{s['start']:04X}_{s['end']:04X}.bin"
        (out / name).write_bytes(s['data'])
        hx = ' '.join(f'{x:02X}' for x in s['data'][:16])
        print(f"{n:02d} {s['start']:04X}-{s['end']:04X} len {len(s['data']):5d} file+{s['off']:5d} sha {hashlib.sha256(s['data']).hexdigest()[:8]}  {hx}")


if __name__ == '__main__':
    main()
