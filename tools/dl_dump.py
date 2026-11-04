#!/usr/bin/env python3
"""Decode the ANTIC display list of a RAM dump: python tools/dl_dump.py <ram.bin> [dl_addr]"""
import sys

d = open(sys.argv[1], "rb").read()
p = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x0A00
i = p
row = 0
while i < p + 0x300:
    b = d[i]
    op = b & 0xF
    flags = ("DLI " if b & 0x80 else "") + ("HS " if b & 0x10 else "")
    if op == 1:
        a = d[i + 1] | d[i + 2] << 8
        print(f"{i:04X} {'JVB' if b & 0x40 else 'JMP'} {a:04X}")
        if b & 0x40:
            break
        i += 3
        continue
    if op == 0:
        print(f"{i:04X} blank{((b >> 4) & 7) + 1} {'DLI' if b & 0x80 else ''}")
        i += 1
        continue
    if b & 0x40:
        a = d[i + 1] | d[i + 2] << 8
        print(f"{i:04X} row{row:3d} m{op:X} LMS {a:04X} {flags}")
        i += 3
    else:
        print(f"{i:04X} row{row:3d} m{op:X} {flags}")
        i += 1
    row += 1
