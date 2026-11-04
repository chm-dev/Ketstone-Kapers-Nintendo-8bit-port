#!/usr/bin/env python3
"""Recursive-descent 6502 disassembler for the Keystone Kapers 8 KiB cart (image $9F80-$BFFF).

Follows JSR/JMP/branches from the entry points; everything unreached is dumped as
data (.byte). Extra entries (jump-table targets found by hand) go in --entry.
Output: docs/atari_disasm.txt style listing with L_xxxx / S_xxxx labels
(S_ = JSR target). Names from tools/symbols.txt ("ADDR name" per line) override labels.

Usage: python tools/rdis.py [--cart assets/atari/keystone_image_9f80_bfff.bin] [--out docs/atari_disasm.txt]
"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dis6502 import OPS, SIZE, fmt, hwname

BASE = 0x9F80
ENTRIES = {0xA000: 'RESET', 0xB0F1: 'VBI', 0xB200: 'DLI', 0xB578: 'IRQ'}


def load_syms(p):
    s = {}
    if p.exists():
        for ln in p.read_text().splitlines():
            ln = ln.split(';')[0].split()
            if len(ln) >= 2:
                s[int(ln[0].lstrip('$'), 16)] = ln[1]
    return s


def trace(d, entries):
    code, jsr, tgts = {}, set(), set()
    work = list(entries)
    while work:
        pc = work.pop()
        while BASE <= pc < BASE + len(d) and pc not in code:
            op = d[pc - BASE]
            if op not in OPS:
                break
            mn, mode = OPS[op]
            n = SIZE[mode]
            if pc - BASE + n > len(d):
                break
            raw = d[pc - BASE:pc - BASE + n]
            v = raw[1] if n == 2 else (raw[1] | raw[2] << 8 if n == 3 else 0)
            code[pc] = (n, mn, mode, v)
            if mode == 'rel':
                t = (pc + 2 + (v - 256 if v > 127 else v)) & 0xFFFF
                tgts.add(t); work.append(t)
            elif mn == 'JSR':
                jsr.add(v); tgts.add(v); work.append(v)
            elif mn == 'JMP' and mode == 'abs':
                tgts.add(v); work.append(v); break
            elif mn in ('JMP', 'RTS', 'RTI', 'BRK'):
                break
            pc += n
    return code, jsr, tgts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cart', default='assets/atari/keystone_image_9f80_bfff.bin')
    ap.add_argument('--out', default='docs/atari_disasm.txt')
    ap.add_argument('--syms', default='tools/symbols.txt')
    ap.add_argument('--entry', action='append', default=[], help='extra entry (hex)')
    ap.add_argument('--entries-file', default='assets/atari/runtime/coverage.txt', help='executed PCs, one hex per line')
    a = ap.parse_args()
    d = Path(a.cart).read_bytes()
    syms = load_syms(Path(a.syms))
    ent = dict(ENTRIES)
    for e in a.entry:
        ent[int(e, 16)] = 'X_' + e
    extra = []
    ef = Path(a.entries_file)
    if ef.exists():
        for ln in ef.read_text().split():
            pc = int(ln, 16)
            if BASE <= pc < BASE + len(d):
                extra.append(pc)
    code, jsr, tgts = trace(d, list(ent) + extra + [k for k in syms if BASE <= k < BASE + len(d) and not syms[k].startswith('d_')])

    def name(addr):
        if addr in syms: return syms[addr]
        if addr in ent: return ent[addr]
        if addr in jsr: return f'S_{addr:04X}'
        if addr in tgts: return f'L_{addr:04X}'
        return None

    lines, pc, covered = [], BASE, sum(n for n, *_ in code.values())
    end = BASE + len(d)
    while pc < end:
        nm = name(pc)
        if nm: lines.append(f'{nm}:')
        if pc in code:
            n, mn, mode, v = code[pc]
            raw = d[pc - BASE:pc - BASE + n]
            op = fmt(mode, v, pc)
            t = None
            if mode == 'rel': t = int(op[1:], 16)
            elif mode in ('abs', 'abx', 'aby'): t = v
            cm = ''
            if t is not None:
                if name(t) and BASE <= t < end:
                    op = op.replace(f'${t:04X}', name(t), 1)
                elif hwname(t): cm = f'  ; {hwname(t)}'
            lines.append(f'{pc:04X}  {" ".join(f"{b:02X}" for b in raw):9} {mn} {op}{cm}')
            pc += n
        else:
            j = pc
            while j < end and j not in code and j - pc < 16 and (j == pc or not name(j)):
                j += 1
            lines.append(f'{pc:04X}  .byte ' + ','.join(f'${x:02X}' for x in d[pc - BASE:j - BASE]))
            pc = j
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text('\n'.join(lines) + '\n')
    print(f'{len(code)} instructions, {covered}/{len(d)} bytes as code ({100*covered/len(d):.0f}%), {len(jsr)} subroutines -> {a.out}')


if __name__ == '__main__':
    main()

