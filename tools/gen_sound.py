#!/usr/bin/env python3
"""Generate src/sound_data.c/.h (NES APU tables) from the POKEY captures + keystone_data.json.

    python tools/gen_sound.py            # writes src/sound_data.c / .h
    python tools/gen_sound.py --check    # exit 1 if the files on disk differ from the generated text

Inputs: assets/data/keystone_data.json (BGM tables B700/B763) and the gitignored captures in
assets/atari/runtime/sound/*.txt (effects 1,2,3,6 are cut from them; effects 4,5 have no capture and
are built from the spec text, see docs/DECISIONS_PENDING.md).  If the captures are missing the checked-in
src/sound_data.c is left alone (--check then only reports it).

POKEY -> APU mapping (NTSC, AUDCTL=0, 64 kHz base = CPU/28):
  pure tone   f = 63921 / (2 (N+1))   -> pulse timer  t = 3.5 (N+1) - 1
  triangle    t = 1.75 (N+1) - 1      (same pitch as the POKEY tone, one octave lower on NES)
  noise       nearest NES noise period to 63921/(N+1)
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "assets/data/keystone_data.json"
CAPDIR = ROOT / "assets/atari/runtime/sound"
OUT_C = ROOT / "src/sound_data.c"
OUT_H = ROOT / "src/sound_data.h"

BGM_STEP_FRAMES = 10
BGM_ENV = [9, 9, 9, 9, 9, 8, 6, 4, 2, 0]      # AUDC3 low nibble over a 10-frame step [V, timeout.txt 70..79]
BGM_LEN = 100                                  # table entries 0..99, loops 1..99
NOISE_PERIODS = [4, 8, 16, 32, 64, 96, 128, 160, 202, 254, 380, 508, 762, 1016, 2034, 4068]  # NTSC CPU cycles
CPU = 1789773.0
POKEY64 = CPU / 28.0

CH_PULSE, CH_NOISE = 0, 1
# effect cfg byte: pulse -> $4000 duty bits (0x00 12.5%, 0x40 25%, 0x80 50%); noise -> $400E bit7 (periodic mode)
END, LOOP = 0, 255


# ----------------------------------------------------------------------------------------------
# captures
def parse_capture(path: Path) -> dict[int, dict[str, int]]:
    """frame -> POKEY register state (carried forward) for frames 0..last logged frame."""
    ev: dict[int, dict[str, int]] = {}
    for line in path.read_text().splitlines():
        m = re.match(r"\s*(\d+)\s+\S+\s+id=\S+\s+st=\S+\s*\|(.*)", line)
        if not m:
            continue
        f = int(m.group(1))
        for kv in m.group(2).split():
            k, v = kv.split("=")
            ev.setdefault(f, {})[k] = int(v, 16)
    state: dict[str, int] = {}
    out: dict[int, dict[str, int]] = {}
    for f in range(0, max(ev) + 1):
        state.update(ev.get(f, {}))
        out[f] = dict(state)
    return out


def ch1_frames(cap: dict[int, dict[str, int]], a: int, b: int) -> list[tuple[int, int]]:
    """(AUDF1, AUDC1) per frame for frames a..b inclusive."""
    return [(cap[f]["AUDF1"], cap[f]["AUDC1"]) for f in range(a, b + 1)]


# ----------------------------------------------------------------------------------------------
# POKEY -> APU conversion
def pulse_timer(n: int) -> int:
    return max(8, round(3.5 * (n + 1) - 1))


def tri_timer(n: int) -> int:
    return round(1.75 * (n + 1) - 1)


def noise_index(n: int, divisor_extra: float = 1.0) -> int:
    f = POKEY64 / (n + 1) / divisor_extra
    best = min(range(16), key=lambda i: abs(math.log(CPU / NOISE_PERIODS[i]) - math.log(f)))
    return best


def convert_step(audf: int, audc: int) -> tuple[int, int, int, int]:
    """-> (channel, cfg, vol, period) for one POKEY (AUDF, AUDC) pair."""
    vol = audc & 15
    dist = audc >> 5
    if dist == 5:                       # pure tone
        return CH_PULSE, 0x80, vol, pulse_timer(audf)
    if dist in (6, 7):                  # poly4 buzz -> 25% pulse
        return CH_PULSE, 0x40, vol, pulse_timer(audf)
    if dist == 1:                       # poly5 -> periodic ("short") noise
        return CH_NOISE, 0x80, vol, noise_index(audf)
    return CH_NOISE, 0x00, vol, noise_index(audf)   # poly17 / poly5+17 -> white noise


def rle(frames: list[tuple[int, int]]) -> list[tuple[int, int, int, int, int]]:
    """per-frame (AUDF, AUDC) -> [(dur, chan, cfg, vol, period)]; vol 0 steps keep their duration."""
    out: list[list[int]] = []
    for audf, audc in frames:
        ch, cfg, vol, per = convert_step(audf, audc)
        if vol == 0:
            per = out[-1][4] if out else 0
        cur = [1, ch, cfg, vol, per]
        if out and out[-1][1:] == cur[1:]:
            out[-1][0] += 1
        else:
            out.append(cur)
    return [tuple(x) for x in out]  # type: ignore[return-value]


# ----------------------------------------------------------------------------------------------
# effects: id -> (prefix steps, loop steps or None)
def build_effects(have_caps: bool):
    eff: dict[int, tuple[list, list | None]] = {}
    if have_caps:
        bonus = parse_capture(CAPDIR / "bonus_end.txt")
        walk = parse_capture(CAPDIR / "walk_all.txt")
        jump = parse_capture(CAPDIR / "jump_walk.txt")
        tout = parse_capture(CAPDIR / "timeout.txt")
        eff[1] = (rle(ch1_frames(bonus, 1, 1)), None)                  # one tick, caller repeats every 4 frames
        eff[2] = (rle(ch1_frames(walk, 6, 7)), None)                   # 2 frames (AUDF F0 then 00)
        eff[3] = (rle(ch1_frames(jump, 20, 20)), rle(ch1_frames(jump, 21, 24)))   # CF,4F,4F,4F loops
        eff[6] = (rle(ch1_frames(tout, 37, 68)), None)                 # death, 32 frames
    else:
        return None
    # 4 pickup / 5 hit: no capture, built from spec section 7 [hypothesis for exact timing]
    pick = []
    for i, (audf, vol) in enumerate([(6, 8), (5, 7), (3, 6), (2, 5), (1, 4)]):
        pick += [(audf, 0x20 | vol)] * 4
    eff[4] = (rle(pick + [(1, 0x20)]), None)
    hit = []
    for vol in range(8, 0, -1):
        hit += [(0x18, 0x20 | vol)] * 4
    hit += [(0x18, 0x20)] * 4                                           # 36 frames total
    eff[5] = (rle(hit), None)
    return eff


def flatten_effects(eff):
    """-> start[7], chan[7], cfg[7], dur[], vol[], lo[], hi[]  (step arrays; LOOP step: lo = target index)."""
    start = [0] * 7
    chan = [0] * 7
    cfg = [0] * 7
    dur: list[int] = []
    vol: list[int] = []
    lo: list[int] = []
    hi: list[int] = []

    def put(d, v, per):
        dur.append(d); vol.append(v); lo.append(per & 255); hi.append(per >> 8)

    for i in range(1, 7):
        pre, loop = eff[i]
        start[i] = len(dur)
        chan[i] = (pre or loop)[0][1]
        cfg[i] = (pre or loop)[0][2]
        for d, ch, c, v, per in pre:
            assert ch == chan[i] and c == cfg[i], f"effect {i} mixes channels"
            assert d <= 254
            put(d, v, per)
        if loop:
            ls = len(dur)
            for d, ch, c, v, per in loop:
                assert ch == chan[i] and c == cfg[i]
                put(d, v, per)
            put(LOOP, 0, ls)
        else:
            put(END, 0, 0)
    return start, chan, cfg, dur, vol, lo, hi


def build_bgm(data: dict):
    r = data["rom"]
    c3, c4 = r["bgm_ch3_audf_B700"], r["bgm_ch4_audf_B763"]
    assert len(c3) == len(c4) == BGM_LEN
    # rest marker: high byte 0xFF
    def conv(tbl, f):
        lo, hi = [], []
        for n in tbl:
            if n == 0:
                lo.append(0); hi.append(0xFF)
            else:
                t = f(n)
                lo.append(t & 255); hi.append(t >> 8)
        return lo, hi
    return conv(c3, pulse_timer), conv(c4, tri_timer)


# ----------------------------------------------------------------------------------------------
def carr(name: str, vals: list[int], typ="uint8_t") -> str:
    rows = []
    for i in range(0, len(vals), 16):
        rows.append("    " + ", ".join(f"{v}" for v in vals[i:i + 16]))
    return f"const {typ} {name}[{len(vals)}] = {{\n" + ",\n".join(rows) + "\n};\n"


def generate(eff, data) -> tuple[str, str]:
    start, chan, cfg, dur, vol, lo, hi = flatten_effects(eff)
    (b3lo, b3hi), (b4lo, b4hi) = build_bgm(data)
    h = f"""/* GENERATED by tools/gen_sound.py - do not edit. NES APU tables from the POKEY captures. */
#ifndef SOUND_DATA_H
#define SOUND_DATA_H
#include <stdint.h>

#define SND_NUM_EFFECTS   6
#define SND_BGM_LEN       {BGM_LEN}      /* entries 0..{BGM_LEN-1}; the tune loops back to 1 */
#define SND_BGM_STEP      {BGM_STEP_FRAMES}       /* frames per BGM step */
#define SND_STEP_END      {END}
#define SND_STEP_LOOP     {LOOP}    /* dur==255: continue at step index snd_step_lo[i] */
#define SND_CH_PULSE      {CH_PULSE}
#define SND_CH_NOISE      {CH_NOISE}
#define SND_BGM_REST      0xFF   /* high byte marking a rest */

/* effects, index 1..6; steps are indexed from snd_eff_start[id] */
extern const uint8_t snd_eff_start[7];
extern const uint8_t snd_eff_chan[7];   /* SND_CH_* */
extern const uint8_t snd_eff_cfg[7];    /* pulse: $4000 duty bits; noise: $400E bit 7 (periodic) */
extern const uint8_t snd_step_dur[{len(dur)}];   /* frames */
extern const uint8_t snd_step_vol[{len(dur)}];   /* 0..15 */
extern const uint8_t snd_step_lo[{len(dur)}];    /* pulse timer low / noise period index */
extern const uint8_t snd_step_hi[{len(dur)}];    /* pulse timer high */

extern const uint8_t snd_bgm_env[{BGM_STEP_FRAMES}];   /* pulse 2 volume per frame of a step */
extern const uint8_t snd_bgm_p_lo[SND_BGM_LEN], snd_bgm_p_hi[SND_BGM_LEN];   /* pulse 2 (POKEY ch3) */
extern const uint8_t snd_bgm_t_lo[SND_BGM_LEN], snd_bgm_t_hi[SND_BGM_LEN];   /* triangle (POKEY ch4) */

#endif
"""
    c = "/* GENERATED by tools/gen_sound.py - do not edit. */\n#include \"sound_data.h\"\n\n"
    c += carr("snd_eff_start", start) + carr("snd_eff_chan", chan) + carr("snd_eff_cfg", cfg)
    c += carr("snd_step_dur", dur) + carr("snd_step_vol", vol) + carr("snd_step_lo", lo) + carr("snd_step_hi", hi)
    c += carr("snd_bgm_env", BGM_ENV)
    c += carr("snd_bgm_p_lo", b3lo) + carr("snd_bgm_p_hi", b3hi)
    c += carr("snd_bgm_t_lo", b4lo) + carr("snd_bgm_t_hi", b4hi)
    return c, h


def main() -> int:
    check = "--check" in sys.argv
    data = json.loads(DATA.read_text())
    have = all((CAPDIR / n).exists() for n in ("bonus_end.txt", "walk_all.txt", "jump_walk.txt", "timeout.txt"))
    eff = build_effects(have)
    if eff is None:
        print("captures missing; keeping existing src/sound_data.*")
        return 0
    c, h = generate(eff, data)
    if check:
        ok = OUT_C.exists() and OUT_C.read_text() == c and OUT_H.read_text() == h
        print("sound_data up to date" if ok else "sound_data OUT OF DATE")
        return 0 if ok else 1
    OUT_C.write_text(c, newline="\n")
    OUT_H.write_text(h, newline="\n")
    print(f"wrote {OUT_C.name} ({len(c)} B text), {OUT_H.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
