#!/usr/bin/env python3
"""Obstacle kinematics model (types 6-11: radio, ball, cart, plane) = the per-floor loop $AACD-$ABC7.

Spec: docs/ATARI_RE_SPEC.md section 9b.  State per floor f (0..3): t=$75+f type, x=$30+f X (HPOS),
fl=$34+f flags (bit3 = moves right, bits 0-2 copy layout), h=$71+f height offset; global p=$8D
(ball bounce phase, ONE counter shared by every ball, floors processed 3,2,1,0).
Per frame inputs: c90 = $90 after this frame's increment, l22 = difficulty, l17 = sound id (>=5 =
Kop hit/dying: nothing moves), l14 = $14 (bit7 = play active), l6E = $6E (type that replaces a
gated-off slot, normally 0).

    python tools/obstacle_model.py tests/golden/obst_lv*.txt     # replays goldens, prints mismatches

Golden format (tools/atari_sprite_probe.py trace): 'frame 090 01E 02C 017 014 08D 06E 06F 030..033
034..037 071..074 075..078 00D..010' header, then one row per frame (RAM after that frame).
Replay: the state is re-seeded from the trace whenever the screen ($1E) changes (spawn uses POKEY
RANDOM and the pickup layout, see spawn_hint()) or a collision/pickup rewrites a slot; every other
frame is predicted from the previous row and compared on t/x/h of floors with types 6-11 and $8D.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ROM = (ROOT / 'assets/atari/keystone_image_9f80_bfff.bin').read_bytes()


def rom(a):
    return _ROM[a - 0x9F80]


def aeeb(l22, thr):
    """S_AEEB: (carry, A).  carry = type enabled; A = speed/tier index."""
    y = l22 >> 2
    if (l22 & 3) >= thr:
        return True, y
    if y == 0:
        return False, 0
    return True, y - 1


def ball_amp(l22):
    """$5F (AAFD-AB1D): 3 for $22 < 4, 12 for 4..11, 3 for >= 12."""
    if l22 < 4 or l22 >= 0x10:
        return 3
    if l22 < 8:
        return 0x0C
    _, a = aeeb(l22, 0)              # 2 or 3
    return 0x0C if a & 1 == 0 else 3


def step(s, c90, l22, l17, l14, l6E=0):
    """One frame of $AA24 for floors without the thief. s = dict(t,x,fl,h lists, p). Returns new s."""
    t, x, fl, h, p = list(s['t']), list(s['x']), list(s['fl']), list(s['h']), s['p']
    for f in (3, 2, 1, 0):
        ty = t[f]
        npx = 0                         # pixels to move this frame
        if ty < 6:
            t[f] = l6E
            if l6E == 0:
                x[f] = 1
            continue
        if ty in (6, 7):                # radio: stationary, pseudo-random frame from code bytes $AAEE+
            ok, _ = aeeb(l22, 1)
            if ok:
                t[f] = 6 + (rom(0xAAEE + (c90 >> 1)) & 1)
            else:
                t[f] = l6E
                if l6E == 0:
                    x[f] = 1
            continue
        if ty == 8:                     # ball: bounce phase, 1 px on odd frames
            amp = ball_amp(l22)
            period = (amp + 8) * 2
            y = p + 1
            if y >= period:
                y = 0
            a = (y - amp) & 0xFF
            hold = False
            if a < 0x10:
                if a >= 8:
                    a ^= 0x0F
                hold = (rom(0xB9A7 + a) & c90) != 0
            if not hold:
                p = y
                if y < period >> 1:
                    h[f] = (h[f] - 1) & 0xFF
                else:
                    h[f] = (h[f] + 1) & 0xFF
            npx = 1 if c90 & 1 else 0
        elif ty == 9:                   # cart
            ok, a = aeeb(l22, 2)
            if not ok:
                t[f] = l6E
                if l6E == 0:
                    x[f] = 1
                continue
            if l22 >= 0x0E:
                npx = 4
            elif a >= 3:
                npx = 1
            else:
                npx = 2 if a & 1 else 1
        elif ty in (10, 11):            # plane: flies 16 px higher, frame toggles every 2 frames
            h[f] = 0x0A
            t[f] = 0x0A + ((c90 & 2) >> 1)
            ok, a = aeeb(l22, 3)
            if not ok:
                t[f] = l6E
                if l6E == 0:
                    x[f] = 1
                continue
            npx = min(a, 3) + 1
        else:
            continue                    # pickups ($0F/$10) and others do not move
        for _ in range(npx):            # $AB9E loop
            if l17 >= 5 or not (l14 & 0x80):
                break
            v = (x[f] + (1 if fl[f] & 8 else 0xFF)) & 0xFF
            if v == 0x18:
                v = 0xD9
            if v >= 0xDA:
                v = 0x20
            x[f] = v
    return dict(t=t, x=x, fl=fl, h=h, p=p)


def spawn_hint(f, screen, l22, pickup_screen, kop_0c):
    """Type + copy layout chosen at a screen change (S_AFBB/AFC2-B0C8), without the RANDOM direction
    flip of carts/planes ($22 ranges below) and without the radio-on-screen-4 rule.  [H, read from code]
    Returns (type, flags $34, x)."""
    if screen == 0:
        return 0, 0, None
    if screen == pickup_screen:
        return 0x0F + (f & 1), 0, 0x78
    a = f + (screen & 3) + 7
    c = a >= 0x0B
    if c:
        a -= 4
    if f == 3:                          # ROR / SBC #0 / ROL on floor 3
        c0 = a & 1
        a = (a >> 1) | (0x80 if c else 0)
        if not c0:
            a = (a - 1) & 0xFF          # SBC #0 with carry clear
            c0 = 1 if a != 0xFF else 0  # borrow chain: carry stays set unless it wrapped
        a = ((a << 1) | c0) & 0xFF
    t = a
    tab = rom(0xB8F5 + t)
    tier_hi = l22 >> 2
    c = (l22 & 3) >= rom(0xBBA2 + t)
    tier = 0 if tier_hi == 0 else min(tier_hi - (0 if c else 1), 3)
    mode = rom(0xBC00 + tab + tier)
    fl = mode | (kop_0c & 0x0C)
    if t == 7:
        return t, fl, (0x58 if fl & 7 else 0x78)
    x = 0x39 if fl & 8 else (0x7C if fl & 4 else 0xBA)
    return t, fl, x


# ---------------------------------------------------------------- golden replay
COLS = None


def parse(path):
    rows = []
    hdr = None
    for ln in Path(path).read_text().splitlines():
        if ln.startswith('frame'):
            hdr = [int(v, 16) for v in ln.split()[1:]]
            continue
        v = ln.split()
        if not v or hdr is None:
            continue
        rows.append(dict(zip(hdr, [int(a, 16) for a in v[1:]])))
    return rows


def state_of(r):
    return dict(t=[r[0x75 + f] for f in range(4)], x=[r[0x30 + f] for f in range(4)],
                fl=[r[0x34 + f] for f in range(4)], h=[r[0x71 + f] for f in range(4)], p=r[0x8D])


def _same_kind(u, v):
    return u == v or {u, v} <= {6, 7} or {u, v} <= {10, 11}


def _diff(pr, ex, types):
    d = [f for f in range(4) if 6 <= types[f] <= 11 and
         (pr['t'][f], pr['x'][f], pr['h'][f]) != (ex['t'][f], ex['x'][f], ex['h'][f])]
    if 8 in types and pr['p'] != ex['p']:
        d.append('p')
    return d


def replay(path, l22, verbose=False):
    """Free-running replay: the model state is carried from frame to frame (one step per $90 increment:
    a screen change costs the game 2 main loops in one video frame) and only re-seeded from the trace
    on a screen change or when a slot is rewritten (pickup, thief, radio hit, gated type).
    A mismatch that is gone on the next row is a 'torn' sample: the RAM dump caught the main loop in the
    middle of the obstacle update (it is not locked to the video frame); counted apart."""
    rows = parse(path)
    n = bad = torn = reseed = 0
    s = state_of(rows[0])
    for i in range(1, len(rows)):
        a, b = rows[i - 1], rows[i]
        if a[0x1E] != b[0x1E] or any(not _same_kind(a[0x75 + f], b[0x75 + f]) for f in range(4)):
            reseed += 1
            s = state_of(b)
            continue
        k = (b[0x90] - a[0x90]) & 0xFF
        for j in range(1, k + 1):
            s = step(s, (a[0x90] + j) & 0xFF, l22, b[0x17], b[0x14], b[0x6E])
        ex = state_of(b)
        types = [a[0x75 + f] for f in range(4)]
        d = _diff(s, ex, types)
        n += sum(1 for f in range(4) if 6 <= types[f] <= 11) + (8 in types)
        if not d:
            continue
        # torn sample?  the free-running model must match again within the next 3 rows
        s2, prev, ok_later = s, b, False
        for c in rows[i + 1:i + 4]:
            if c[0x1E] != b[0x1E] or any(not _same_kind(prev[0x75 + f], c[0x75 + f]) for f in range(4)):
                break
            for j in range(1, ((c[0x90] - prev[0x90]) & 0xFF) + 1):
                s2 = step(s2, (prev[0x90] + j) & 0xFF, l22, c[0x17], c[0x14], c[0x6E])
            if not _diff(s2, state_of(c), [c[0x75 + f] for f in range(4)]):
                ok_later = True
                break
            prev = c
        if ok_later:
            torn += len(d)
            continue
        bad += len(d)
        if verbose and bad <= 12:
            print(f'  row {i} ({b[0x90]:02X}): ' + '; '.join(
                f'floor {f}: model t{s["t"][f]:X} x{s["x"][f]:02X} h{s["h"][f]:02X} / atari t{ex["t"][f]:X} '
                f'x{ex["x"][f]:02X} h{ex["h"][f]:02X}' if f != 'p' else f'$8D model {s["p"]:02X} atari {ex["p"]:02X}'
                for f in d))
        s = ex                          # re-sync after a real mismatch
    return n, bad, torn, reseed


def write_json():
    """assets/data/obstacles.json: ROM tables + derived per-level behaviour of the obstacle types."""
    import json

    def tb(a, n):
        return [rom(a + i) for i in range(n)]

    names = {6: 'radio_a', 7: 'radio_b', 8: 'ball', 9: 'cart', 10: 'plane_a', 11: 'plane_b',
             15: 'suitcase', 16: 'moneybag'}
    per_level = []
    for l22 in range(17):
        e = {'l22': l22, 'level_shown': l22 + 1}
        for t, thr in ((7, 1), (8, 0), (9, 2), (10, 3)):
            ok, a = aeeb(l22, thr) if thr else (True, l22 >> 2)
            hi = l22 >> 2
            c = (l22 & 3) >= rom(0xBBA2 + t)
            tier = 0 if hi == 0 else min(hi - (0 if c else 1), 3)
            mode = rom(0xBC00 + rom(0xB8F5 + t) + tier)
            d = {'enabled': ok, 'copy_mode': mode}
            if t == 8:
                d.update(amp=ball_amp(l22), period=(ball_amp(l22) + 8) * 2, px_per_frame=0.5)
            elif t == 9:
                d['px_per_frame'] = 4 if l22 >= 0x0E else (1 if a >= 3 else (2 if a & 1 else 1))
                d['random_direction'] = 6 <= l22 < 0x0A or l22 >= 0x0E
            elif t == 10:
                d['px_per_frame'] = min(a, 3) + 1
                d['random_direction'] = l22 >= 7
            elif t == 7:
                d['removed_on_screen4'] = l22 < 5
                if not l22 < 5:
                    d['screen4_copy_mode'] = 4
            e[{7: 'radio', 8: 'ball', 9: 'cart', 10: 'plane'}[t]] = d
        per_level.append(e)
    out = {
        'source': 'tools/obstacle_model.py --json; code $AA24-$ABC7 (motion), $AFBB-$B0C8 (spawn), '
                  '$A789-$A7F4/$A8C1 (hits); spec section 9b',
        'types': {str(k): v for k, v in names.items()},
        'gate_threshold_BBA2_by_type': {str(t): rom(0xBBA2 + t) for t in (7, 8, 9, 10)},
        'copy_mode_table_by_type_and_tier': {str(t): tb(0xBC00 + rom(0xB8F5 + t), 4) for t in (7, 8, 9, 10)},
        'copy_modes': {'0': [0], '4': [0, 64], '6': [0, 32, 64], '7': [0, 32],
                       'mode4_wrap': 'when X >= $A0 the 2nd copy is at X-$81 ($34 bit3=0) or X-$7A (bit3=1)'},
        'spawn': {
            'type': 'screen 0: none; screen == $85[f]: pickup $0F+(f&1) at X=$78; else t=f+(s&3)+7, t>=11 -> t-4, '
                    'floor 3 ROR/SBC/ROL remap (spawn_hint)',
            'flags': '$34 = copy_mode(type, tier) | ($0C & $0C) (Kop facing at entry: bit3 = Kop walking left '
                     '-> obstacles move right)',
            'x': {'moving_right': 0x39, 'moving_left': 0xBA, 'moving_left_2copies': 0x7C, 'radio': 0x58,
                  'radio_single': 0x78, 'random_flip': 0x7A, 'pickup': 0x78},
            'height_71': 0x1A, 'resets': '$8D = 0, $0D+f = 0, $90 &= $F3'},
        'tier': 'tier = 0 if $22>>2 == 0 else min(($22>>2) - (($22&3) < BBA2[type]), 3)',
        'enable_rule': 'S_AEEB(thr): enabled if ($22&3) >= thr or ($22>>2) > 0; speed index A = $22>>2, '
                       'minus 1 when ($22&3) < thr',
        'motion': {
            'step': 'x += 1 if $34 bit3 else -1, per pixel; x == $18 -> $D9, x >= $DA -> $20; '
                    'no motion while $17 >= 5 (hit/death) or $14 bit7 clear',
            'radio': 'stationary; frame 6 + (byte[$AAEE + ($90>>1)] & 1) (code bytes used as noise)',
            'ball': 'phase $8D (one global counter) +1 per frame wrapping at period=(amp+8)*2; '
                    'a=(phase-amp)&255, if a<16: a^=15 if a>=8, hold (no phase/height change) when '
                    'B9A7[a] & $90 != 0; first half of the period $71-- (up), second half $71++; '
                    '1 px on odd $90',
            'cart': 'every frame, px from per_level',
            'plane': '$71 = $0A (16 px above the floor objects), frame $0A + (($90&2)>>1), px from per_level',
        },
        'B9A7_ball_hold_mask': tb(0xB9A7, 8),
        'radio_hit': {'copy_x_BEF2': tb(0xBEF2, 3), 'clear_mask_BEF8': tb(0xBEF8, 3),
                      'mask_after_spawn_BEF1_by_mode': tb(0xBEF1, 8),
                      'new_mode_BEE1_by_mask': tb(0xBEE1, 8), 'new_x_BEE9_by_mask': tb(0xBEE9, 8),
                      'rule': 'a radio is hit when Kop jump height < 6; the copy i with BEF2[i]-KopX < $11 '
                              'is cleared from $6F (bit0=$98, bit1=$78, bit2=$58); after the hit freeze '
                              '$30=BEE9[$6F], $34=BEE1[$6F]'},
        'collision': {'1-5': 'thief: catch, +1000, bonus phase', '6-7': 'hit unless jump height >= 6',
                      '8-9': 'hit (36-frame freeze, time drain)', '10-11': 'death', '12-14': 'nothing',
                      '15-16': 'pickup +B5F7[f] hundreds'},
        'per_level': per_level,
    }
    (ROOT / 'assets/data/obstacles.json').write_text(json.dumps(out, indent=1))
    print('wrote assets/data/obstacles.json')


def main():
    if sys.argv[1:] == ['--json']:
        write_json()
        return 0
    paths = sys.argv[1:] or sorted(str(p) for p in (ROOT / 'tests/golden').glob('obst_lv*.txt'))
    tot = totbad = 0
    for p in paths:
        l22 = int(Path(p).stem.split('lv')[-1][:2], 16)
        n, bad, torn, rs = replay(p, l22, verbose=True)
        print(f'{Path(p).name}: $22={l22:02X} {n - bad - torn}/{n} floor-frames match, {torn} torn samples, '
              f'{bad} mismatches ({rs} reseeds)')
        tot += n
        totbad += bad
    print(f'TOTAL {tot - totbad}/{tot} (baseline: {BASELINE_BAD} unexplained = long torn samples + spawn frame)')
    return 0 if totbad <= BASELINE_BAD else 1


BASELINE_BAD = 17      # 2026-11-04 goldens obst_lv03/07/0B/0F; a rise means a regression in step()


if __name__ == '__main__':
    raise SystemExit(main())
