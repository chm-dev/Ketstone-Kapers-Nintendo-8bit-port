#!/usr/bin/env python3
"""Host test of the sound tables: replays src/sound.c's logic in Python from the generated tables and
compares with the POKEY captures (frame counts, step counts, BGM notes/envelope).  Run: python tests/test_sound.py"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import gen_sound as g  # noqa: E402

data = json.loads(g.DATA.read_text())
have_caps = g.CAPDIR.exists() and (g.CAPDIR / "timeout.txt").exists()
fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails += 1


def tables():
    eff = g.build_effects(have_caps)
    return g.flatten_effects(eff), g.build_bgm(data)


if not have_caps:
    print("captures missing: only checking the committed tables parse")
    sys.exit(0)

(start, chan, cfg, dur, vol, lo, hi), ((p_lo, p_hi), (t_lo, t_hi)) = tables()


class Eff:
    """Python twin of eff_load/snd_tick for the effect voice: yields (chan, vol, timer) per frame."""

    def __init__(self, i):
        self.i, self.pos, self.wait, self.done = i, start[i], 0, False
        self.cur = None
        self.load()

    def load(self):
        d = dur[self.pos]
        if d == g.LOOP:
            self.pos = lo[self.pos]
            d = dur[self.pos]
        if d == g.END:
            self.done = True
            self.cur = None
            return
        self.wait = d
        self.cur = (chan[self.i], vol[self.pos], lo[self.pos] | (hi[self.pos] << 8))
        self.pos += 1

    def tick(self):
        if self.done:
            return
        self.wait -= 1
        if self.wait == 0:
            self.load()


def play(i, frames):
    e, out = Eff(i), []
    for _ in range(frames):
        out.append(e.cur)
        e.tick()
    return out, e


def expected(cap, a, b):
    exp = []
    for audf, audc in g.ch1_frames(cap, a, b):
        ch, c, v, per = g.convert_step(audf, audc)
        exp.append((ch, v, per) if v else None)
    return exp


def norm(x):   # silent frames: only compare "silent"
    return None if (x is None or x[1] == 0) else x


tout = g.parse_capture(g.CAPDIR / "timeout.txt")
walk = g.parse_capture(g.CAPDIR / "walk_all.txt")
jump = g.parse_capture(g.CAPDIR / "jump_walk.txt")
bonus = g.parse_capture(g.CAPDIR / "bonus_end.txt")

# --- effects vs captures -----------------------------------------------------------------
out, e = play(6, 40)
exp = expected(tout, 37, 68)
check([norm(x) for x in out[:32]] == [norm(x) for x in exp], "death: 32 frames match the capture timeline")
check(e.done and out[32:] == [None] * 8, "death: voice idle after 32 frames")
n6 = 0
p = start[6]
while dur[p] != g.END:
    n6 += 1; p += 1
check(n6 == 12, f"death: {n6} steps (4 AUDF x vol segments)")

out, e = play(2, 6)
check(e.done and sum(dur[start[2]:start[2] + 2]) == 2, "walk: 2 frames then idle")

out, e = play(1, 4)
check(out[0] and out[0][1] == 10 and out[1] is None, "bonus tick: 1 frame at vol 10")
check(bonus[1]["AUDF1"] == 3 and bonus[1]["AUDC1"] == 0xCA, "bonus capture: AUDF 03 AUDC CA")

out, e = play(3, 40)
exp = expected(jump, 20, 36)
check([norm(x) for x in out[:17]] == [norm(x) for x in exp], "jump: first 17 frames match capture (20..36)")
check(not e.done, "jump: loops until snd_play(0)")
period = [jump[f]["AUDF1"] for f in range(22, 37)]
check(period == [0x4F, 0x4F, 0x4F, 0xCF] * 3 + [0x4F, 0x4F, 0x4F], "jump capture pattern 4F,4F,4F,CF")

out, e = play(4, 40)
check(sum(1 for x in out if x and x[1]) == 20 and e.done, "pickup: 20 audible frames, 5 steps x 4 [hypothesis]")
out, e = play(5, 60)
check(sum(1 for x in out if x and x[1]) == 32 and sum(d for d in dur[start[5]:start[6]] if d != g.END) == 36,
      "hit: 36 frames (9 x 4), last 4 silent")
check(all(dur[i] <= 254 or dur[i] == g.LOOP for i in range(len(dur))), "step durations fit a byte")
check(len(dur) < 256, f"{len(dur)} steps")

# --- BGM -----------------------------------------------------------------------------------
r3, r4 = data["rom"]["bgm_ch3_audf_B700"], data["rom"]["bgm_ch4_audf_B763"]
check(len(r3) == len(r4) == g.BGM_LEN == 100, "bgm: 100 steps in both tables")
for i in range(100):
    if r3[i] == 0:
        assert p_hi[i] == 0xFF
    else:
        assert (p_lo[i] | p_hi[i] << 8) == g.pulse_timer(r3[i])
    if r4[i] == 0:
        assert t_hi[i] == 0xFF
    else:
        assert (t_lo[i] | t_hi[i] << 8) == g.tri_timer(r4[i])
check(max(g.pulse_timer(n) for n in r3 if n) < 2048 and max(g.tri_timer(n) for n in r4 if n) < 2048, "bgm: timers < 2048")


def bgm_run(idx, frames):
    """frames of (AUDF3-equivalent index, vol) like snd_tick: step advances every 10 frames, loop to 1."""
    out, f = [], 0
    for _ in range(frames):
        out.append((idx, g.BGM_ENV[f]))
        f += 1
        if f == g.BGM_STEP_FRAMES:
            f = 0
            idx += 1
            if idx >= g.BGM_LEN:
                idx = 1
    return out


# capture timeout.txt frames 0..68: notes change every 10 frames starting at table idx 14
seq = bgm_run(14, 69)
ok = True
for f in range(69):
    i = seq[f][0]
    if tout[f]["AUDF3"] != r3[i] or tout[f]["AUDF4"] != r4[i]:
        ok = False
        print("  mismatch frame", f, "idx", i, tout[f]["AUDF3"], r3[i], tout[f]["AUDF4"], r4[i])
check(ok, "bgm: AUDF3/AUDF4 follow B700/B763 at 10 frames/step (capture frames 0..68, idx 14..20)")
# after the level restart (frame 70) the envelope is 9,9,9,9,9,8,6,4,2,0
env_cap = [tout[f]["AUDC3"] & 15 for f in range(70, 80)]
check(env_cap == g.BGM_ENV, f"bgm: envelope {env_cap} == table")
cands = [i for i in range(1, 100) if r3[i] == tout[70]["AUDF3"] and r4[i] == tout[70]["AUDF4"]]
check(bool(cands), f"bgm: restart note (frame 70) found at table idx {cands}")
ok = False
for i in cands:
    s2 = bgm_run(i, 60)
    if all(f not in tout or (tout[f]["AUDF3"] == r3[s2[f-70][0]] and (tout[f]["AUDC3"] & 15) == s2[f-70][1]) for f in range(70, 130)):
        ok = True
check(ok, "bgm: second segment (frames 70..) matches AUDF3 and envelope")
# loop: index 99 -> 1
s = bgm_run(99, 11)
check(s[0][0] == 99 and s[10][0] == 1, "bgm: wraps from 99 to 1")

# --- generated files in sync --------------------------------------------------------------
c, h = g.generate(g.build_effects(True), data)
check(g.OUT_C.read_text() == c and g.OUT_H.read_text() == h, "src/sound_data.c/.h match the generator")

print("FAILED" if fails else "all sound tests passed")
sys.exit(1 if fails else 0)
