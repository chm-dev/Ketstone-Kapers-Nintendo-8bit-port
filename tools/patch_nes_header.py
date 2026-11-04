#!/usr/bin/env python3
"""Normalise the iNES header produced by GBDK's lcc/makenes pipeline.

GBDK 4.5.0 always passes ``-a 1`` to makenes, which sets the "alternative
nametable layout" bit (byte 6, bit 3).  For mapper 30 that bit means the
four-screen cartridge-VRAM layout, which this ROM does not have.  The port
needs vertical mirroring (two side-by-side nametables: the HUD in $2000 and
the playfield in $2400), so write layout 01 in the low nibble of byte 6
while keeping the mapper number intact.

Run automatically from build.ps1 / the Makefile.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_nes_header.py <rom.nes>", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    rom = bytearray(path.read_bytes())
    if len(rom) < 16 or rom[:4] != b"NES\x1a":
        raise SystemExit(f"{path}: missing iNES header")

    mapper = ((rom[6] >> 4) & 0x0F) | (rom[7] & 0xF0)
    if mapper != 30:
        raise SystemExit(f"{path}: expected mapper 30, found {mapper}")

    before = rom[6]
    rom[6] = (rom[6] & 0xF0) | 0x01  # vertical mirroring; no battery/four-screen
    path.write_bytes(rom)
    print(
        f"header byte6 0x{before:02X} -> 0x{rom[6]:02X} "
        f"(mapper {mapper}, vertical mirroring)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
