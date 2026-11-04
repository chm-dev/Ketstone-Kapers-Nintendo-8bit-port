#!/usr/bin/env python3
"""Tiny 6502 disassembler (official opcodes + a few common illegals as .byte).

Usage: python tools/dis6502.py FILE --base 0x0601 [--start 0x0601] [--len N] [--labels]
With --labels, branch/jump targets inside the range get L_xxxx labels.
Known Atari hardware registers are annotated.
"""
import argparse, re
from pathlib import Path

OPS = {}
def _def(mn, modes):
    for mode, op in modes.items():
        OPS[op] = (mn, mode)

_def('ADC', dict(imm=0x69, zp=0x65, zpx=0x75, abs=0x6D, abx=0x7D, aby=0x79, inx=0x61, iny=0x71))
_def('AND', dict(imm=0x29, zp=0x25, zpx=0x35, abs=0x2D, abx=0x3D, aby=0x39, inx=0x21, iny=0x31))
_def('ASL', dict(acc=0x0A, zp=0x06, zpx=0x16, abs=0x0E, abx=0x1E))
_def('BIT', dict(zp=0x24, abs=0x2C))
_def('CMP', dict(imm=0xC9, zp=0xC5, zpx=0xD5, abs=0xCD, abx=0xDD, aby=0xD9, inx=0xC1, iny=0xD1))
_def('CPX', dict(imm=0xE0, zp=0xE4, abs=0xEC))
_def('CPY', dict(imm=0xC0, zp=0xC4, abs=0xCC))
_def('DEC', dict(zp=0xC6, zpx=0xD6, abs=0xCE, abx=0xDE))
_def('EOR', dict(imm=0x49, zp=0x45, zpx=0x55, abs=0x4D, abx=0x5D, aby=0x59, inx=0x41, iny=0x51))
_def('INC', dict(zp=0xE6, zpx=0xF6, abs=0xEE, abx=0xFE))
_def('JMP', dict(abs=0x4C, ind=0x6C))
_def('JSR', dict(abs=0x20))
_def('LDA', dict(imm=0xA9, zp=0xA5, zpx=0xB5, abs=0xAD, abx=0xBD, aby=0xB9, inx=0xA1, iny=0xB1))
_def('LDX', dict(imm=0xA2, zp=0xA6, zpy=0xB6, abs=0xAE, aby=0xBE))
_def('LDY', dict(imm=0xA0, zp=0xA4, zpx=0xB4, abs=0xAC, abx=0xBC))
_def('LSR', dict(acc=0x4A, zp=0x46, zpx=0x56, abs=0x4E, abx=0x5E))
_def('ORA', dict(imm=0x09, zp=0x05, zpx=0x15, abs=0x0D, abx=0x1D, aby=0x19, inx=0x01, iny=0x11))
_def('ROL', dict(acc=0x2A, zp=0x26, zpx=0x36, abs=0x2E, abx=0x3E))
_def('ROR', dict(acc=0x6A, zp=0x66, zpx=0x76, abs=0x6E, abx=0x7E))
_def('SBC', dict(imm=0xE9, zp=0xE5, zpx=0xF5, abs=0xED, abx=0xFD, aby=0xF9, inx=0xE1, iny=0xF1))
_def('STA', dict(zp=0x85, zpx=0x95, abs=0x8D, abx=0x9D, aby=0x99, inx=0x81, iny=0x91))
_def('STX', dict(zp=0x86, zpy=0x96, abs=0x8E))
_def('STY', dict(zp=0x84, zpx=0x94, abs=0x8C))
for mn, op in dict(BPL=0x10, BMI=0x30, BVC=0x50, BVS=0x70, BCC=0x90, BCS=0xB0, BNE=0xD0, BEQ=0xF0).items():
    OPS[op] = (mn, 'rel')
for mn, op in dict(BRK=0x00, CLC=0x18, CLD=0xD8, CLI=0x58, CLV=0xB8, DEX=0xCA, DEY=0x88, INX=0xE8, INY=0xC8,
                   NOP=0xEA, PHA=0x48, PHP=0x08, PLA=0x68, PLP=0x28, RTI=0x40, RTS=0x60, SEC=0x38, SED=0xF8,
                   SEI=0x78, TAX=0xAA, TAY=0xA8, TSX=0xBA, TXA=0x8A, TXS=0x9A, TYA=0x98).items():
    OPS[op] = (mn, 'imp')
SIZE = dict(imp=1, acc=1, imm=2, zp=2, zpx=2, zpy=2, inx=2, iny=2, rel=2, abs=3, abx=3, aby=3, ind=3)

HW = {0xD000: 'GTIA', 0xD200: 'POKEY', 0xD300: 'PIA', 0xD400: 'ANTIC'}
def hwname(a):
    for base, n in HW.items():
        if base <= a < base + 0x100:
            return f'{n}+{a - base:02X}'
    if 0xD600 <= a < 0xD700:
        return f'D6xx+{a - 0xD600:02X}'
    return None


def fmt(mode, v, pc):
    if mode == 'imp': return ''
    if mode == 'acc': return 'A'
    if mode == 'imm': return f'#${v:02X}'
    if mode == 'zp': return f'${v:02X}'
    if mode == 'zpx': return f'${v:02X},X'
    if mode == 'zpy': return f'${v:02X},Y'
    if mode == 'inx': return f'(${v:02X},X)'
    if mode == 'iny': return f'(${v:02X}),Y'
    if mode == 'rel': return f'${(pc + 2 + (v - 256 if v > 127 else v)) & 0xFFFF:04X}'
    if mode == 'abs': return f'${v:04X}'
    if mode == 'abx': return f'${v:04X},X'
    if mode == 'aby': return f'${v:04X},Y'
    if mode == 'ind': return f'(${v:04X})'


def disasm(data, base, start=None, length=None):
    pc = start if start is not None else base
    end = pc + (length if length is not None else len(data) - (pc - base))
    out = []
    while pc < end:
        o = pc - base
        op = data[o]
        if op not in OPS:
            out.append((pc, [op], '.byte', f'${op:02X}', None)); pc += 1; continue
        mn, mode = OPS[op]
        n = SIZE[mode]
        if o + n > len(data): break
        raw = list(data[o:o + n])
        v = raw[1] if n == 2 else (raw[1] | raw[2] << 8 if n == 3 else 0)
        tgt = None
        if mode == 'rel' or (mn in ('JMP', 'JSR') and mode == 'abs'):
            tgt = int(fmt(mode, v, pc)[1:], 16)
        out.append((pc, raw, mn, fmt(mode, v, pc), tgt if tgt is not None else (v if mode in ('abs', 'abx', 'aby') else None)))
        pc += n
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file')
    ap.add_argument('--base', type=lambda x: int(x, 0), required=True)
    ap.add_argument('--start', type=lambda x: int(x, 0))
    ap.add_argument('--len', type=lambda x: int(x, 0))
    ap.add_argument('--labels', action='store_true')
    a = ap.parse_args()
    data = Path(a.file).read_bytes()
    ins = disasm(data, a.base, a.start, a.len)
    lo = ins[0][0]; hi = ins[-1][0]
    targets = {i[4] for i in ins if i[2] in ('JMP', 'JSR') or i[2].startswith('B') and i[2] not in ('BIT', 'BRK')
               if i[4] is not None and lo <= i[4] <= hi}
    for pc, raw, mn, op, tgt in ins:
        lab = f'L_{pc:04X}:' if a.labels and pc in targets else ''
        if a.labels and tgt is not None and tgt in targets:
            op = re.sub(r'\$[0-9A-F]{4}', f'L_{tgt:04X}', op, count=1)
        c = ''
        if tgt is not None and hwname(tgt):
            c = f'  ; {hwname(tgt)}'
        print(f'{lab:9}{pc:04X}  {" ".join(f"{b:02X}" for b in raw):9} {mn} {op}{c}')


if __name__ == '__main__':
    main()
