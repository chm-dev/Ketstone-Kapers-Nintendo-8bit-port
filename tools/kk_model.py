#!/usr/bin/env python3
"""Reference model of Keystone Kapers (Atari) logic, derived from the disassembly and verified
against live Altirra traces (tests/golden/*.txt; run tests/test_kk_model.py, tests/test_thief_model.py).

Scope so far: Kop walking / ducking / jumping / screen wrap / escalators, thief path, timer.
Names follow docs/ATARI_RE_SPEC.md; zero-page addresses are in comments.
"""
from __future__ import annotations

from dataclasses import dataclass, field

B8D4 = (0x90, 0x65, 0x90, 0xA8)       # escalator base X per floor
B8D7 = (0xA8, 0x80, 0xA8, 0x6E)       # $0C value while riding per floor (A8 = left, 80 = right)
B9E3 = (0x07, 0x00, 0x07, 0xE0)       # screen holding the escalator of floor f (floor 3: none)
BBA1 = (0x04, 0x0B, 0x14, 0x0B)       # elevator (screen 4) path index per car floor
BBA2 = (0x0B, 0x14, 0x0B, 0x04)       # thief path position that blocks the car leaving for the next stop


@dataclass
class Kop:
    xs: list = field(default_factory=lambda: [0x7A, 0, 0, 0])   # $2C+floor
    path: int = 0          # $1D  floor*8 + path index
    screen: int = 0        # $1E
    face: int = 0          # $0C  0 right, 8 left, bit7 set = on escalator ($80 right / $A8 left)
    pose: int = 6          # $20  1..5 walk, 2 jump, 6 stand, 7 duck
    jump: int = 0          # $19
    c1c: int = 0           # $1C  low 5 bits = jump height / escalator step, bits 5-7 = floor marker
    latch: int = 0         # $18  trigger latch (FF = held since last jump)
    stick: tuple = (False, False, False, False)  # $62 latched (up, down, left, right)
    thief_path: int = 0x0B  # $1F, only used by the escalator entry check / elevator interlock
    e8e: int = 0           # $8E elevator phase counter
    e6b: int = 0           # $6B elevator trip counter (car floor = [0,1,2,1][e6b&3])
    _ad_pending: bool = False

    @property
    def floor(self):
        return (self.path >> 3) & 3

    @property
    def x(self):
        return self.xs[self.floor]

    @x.setter
    def x(self, v):
        self.xs[self.floor] = v & 0xFF

    @property
    def height(self):
        return self.c1c & 0x1F

    def riding(self):
        return bool(self.face & 0x80) and not (self.face & 0x40)

    @property
    def car_floor(self):
        v = self.e6b & 3
        return 1 if v == 3 else v

    def step(self, stick, fire, c90, c8f=0):
        # AD0F block of the previous frame (runs after the main loop waits for the top of the frame,
        # i.e. after the sampling point used by the traces)
        if self._ad_pending:
            self._elevator_logic()
        # A528..A53D: elevator phase counter (every frame, any screen)
        y = 1 if (self.screen == 4 and self.car_floor == self.floor) else 7
        a = self.e8e
        if a < 0x80 or a >= 0xF0 or (y & c90) == 0:
            self.e8e = (a + 1) & 0xFF
            if self.e8e == 0:
                self.e6b = (self.e6b + 1) & 0xFF
        self._step(stick, fire, c90, c8f)
        self._ad_pending = self.screen == 4
        # A877: while height >= 13 the floor above gets a copy of Kop (its X slot mirrors Kop's X)
        if (self.c1c & 0x1F) >= 13 and self.floor < 3:
            self.xs[self.floor + 1] = self.xs[self.floor]

    def _step(self, stick, fire, c90, c8f=0):
        """One main-loop pass. stick = (up, down, left, right) booleans, fire bool,
        c90 = $90 during logic (value before this frame's increment), c8f = $8F during logic (after increment)."""
        if self.riding():
            self._ride_tick(c8f)
            return
        if (self.face & 0xC0) == 0xC0:
            self._in_car(stick)
            return
        up, down, left, right = self.stick if self.jump else stick
        wrapped = False
        walking = False
        # --- movement (A5C0..A689)
        if down:
            self.pose = 7
        elif left:
            self.face = 8
            self.x -= 1
            lim = 0x2D if self.screen == 7 else 0x2A
            if self.x <= lim:
                if self.screen == 7:
                    self.x = 0x2F
                else:
                    self.x = 0xCF
                    self._wrap(+1)
                    wrapped = True
            walking = True
        elif right:
            self.face = 0
            y = self.x + 1
            if self.screen == 0:
                self.x = 0xC9 if y >= 0xCB else y
            elif y < 0xCC:
                self.x = y
            else:
                self.x = 0x2B
                self._wrap(-1)
                wrapped = True
            walking = True
        else:
            self.pose = 6
            # A653..A687: elevator entry (standing, up pressed, doors open, car here, x in $77..$79)
            if (self.screen == 4 and self.jump == 0 and (self.e8e & 0x80) and self.e8e < 0xF0
                    and self.car_floor == self.floor and 0x77 <= self.x <= 0x79 and stick[0]):
                self.c1c = (self.c1c + 2) & 0xFF
                self.face |= 0xE0
        if walking:
            if not wrapped:
                if self.x & 1:
                    self.pose += 1
                    if self.pose >= 6:
                        self.pose = 1
            self._escalator_entry(c8f)
        # --- jump (A704..A76C)
        if self.riding():
            return
        if self.jump:
            old = self.jump
            if ((old - 6) & 0xFF) >= 6 or (c90 & 3) == 0:
                self.jump = old - 1
                self.c1c = (self.c1c + (1 if self.jump >= 9 else -1)) & 0xFF
            self.pose = 2
            if self.jump >= 0x10:
                self.stick = stick  # re-latched while $19 >= $10 (A735..A75F)
        else:
            if not fire:
                self.latch = 0
            elif not self.latch:
                self.jump = 0x12
                self.stick = stick
                self.latch = 0xFF

    def _elevator_logic(self):
        """AD0F..AD62 (only while Kop is on screen 4): door window / departure / thief interlock."""
        a = self.e8e & 0x7F
        if a < 0x70 or ((a >> 2) & 3) != 1:
            return
        if not (self.e8e & 0x80):
            self.e8e = 0x80                        # $74-$77: open the doors
            return
        if self.thief_path == BBA2[self.e6b & 3]:   # thief on the next stop: car waits at $F4
            self.e8e = (self.e8e - 1) & 0xFF
            return
        self.e6b = (self.e6b + 1) & 0xFF
        self.e8e = 0

    def _in_car(self, stick):
        """A564..A5B9: Kop inside the car follows the car floor; down in the door window gets out."""
        cf = self.car_floor
        self.c1c = ((cf << 5) | 2) & 0xFF
        self.xs[cf] = self.x
        self.path = BBA1[cf]
        if self.e8e & 0x80 and self.e8e < 0xF0 and stick[1]:
            self.c1c = (self.c1c - 2) & 0xFF
            self.face &= 0x0F

    def _wrap(self, d):
        # d=+1: moving left (screen++), -1: moving right. $1D path index runs opposite on odd floors.
        step = d if self.floor % 2 == 0 else -d
        self.path = (self.path + step) & 0xFF
        self.screen += d

    def _escalator_entry(self, c8f):
        f = self.floor
        if self.screen != B9E3[f] or self.thief_path == self.path:
            return
        h = self.c1c & 0x1F
        if self.screen & 1:
            h ^= 0xFF
        v = (self.x + ((~((h + B8D4[f]) & 0xFF)) & 0xFF)) & 0xFF
        if v >= 2:
            return
        self.jump = 0                                  # $19 = v>>1
        self.latch = 0xFC                              # $18
        self.c1c = (self.c1c & 0xFC) | ((c8f >> 2) & 3)
        h = self.c1c & 0x1F
        if f != 1:
            h = ((~h) & 0xFF) + 3
        self.x = (h + B8D4[f]) & 0xFF
        self.face = B8D7[f]
        self.pose = 6

    def _ride_tick(self, c8f):
        if c8f & 3:
            return
        if self.face == 0xA8:
            self.x -= 1
        else:
            self.x += 1
        self.c1c = (self.c1c + 1) & 0xFF
        if (self.c1c & 0x1F) == 0:
            self.path += 1
            self.face &= 0x0F


@dataclass
class Thief:
    """Thief ($1B x, $1F path, $63 anim) and level timer ($28), A973..AA20 and A537..A554.
    Kop-relative flee/reverse override ($58 at AA06..AA20) is implemented for the same-floor and
    higher-floor cases from the disassembly but is not yet covered by a golden trace."""
    x: int = 0xB1
    path: int = 0x0B       # $1F
    anim: int = 3          # $63
    time: int = 0x50       # $28 BCD
    escaped: bool = False  # $1A bit7

    @property
    def screen(self):      # $11 (fold)
        v = self.path & 0x0F
        return v ^ 0x0F if v >= 8 else v

    def dir_left(self, kop_path=None, kop_screen=None):
        """$58 bit3 (True = moving left / decreasing X)."""
        floor_bits = self.path & 0x18
        d = (floor_bits ^ 8) & 8
        if kop_path is not None:
            kf = kop_path & 0x18
            if kf == floor_bits:
                d = 8 if self.screen >= kop_screen else 0
            elif kf > floor_bits:
                d ^= 8
        return bool(d)

    def step(self, c90_after_inc, kop_path=None, kop_screen=None):
        c90 = c90_after_inc & 0xFF
        if (c90 & 1) and not self.escaped:
            y = self.x
            if not self.dir_left(kop_path, kop_screen):
                y += 1
                if y >= 0xCD:
                    if self.path == 0x1F:
                        self.escaped = True
                        return
                    y = 0x2B
                    self._turn(+1 if (self.path & 8) else -1, y_wrap=y)
                    y = self._y
            else:
                y -= 1
                if y < 0x29:
                    y = 0xCF
                    self._turn(-1 if (self.path & 8) else +1, y_wrap=y)
                    y = self._y
            self.x = y
            if y & 1:
                self.anim = self.anim + 1 if self.anim + 1 < 6 else 1

    def _turn(self, d, y_wrap):
        self._y = y_wrap
        self.path += d
        if self.path < 0:
            self.path = 0
            self._y = 0xCA
            return
        low = self.path & 7
        if (d > 0 and low == 0) or (d < 0 and low == 7):
            # floor boundary: Y = ~Y + $F8 + 1  (carry set by the equal compare)
            self._y = ((~y_wrap & 0xFF) + 0xF8 + 1) & 0xFF

    def tick_timer(self, c90_after_inc):
        if (c90_after_inc - 1) & 0x7F == 0 and self.time > 0:
            lo = (self.time & 0x0F) - 1
            self.time = (self.time & 0xF0) | lo if lo >= 0 else ((self.time - 0x10) & 0xF0) | 9


def parse_plan(plan):
    out = []
    for item in plan.split(","):
        spec, _, n = item.partition(":")
        d, _, fire = spec.partition("+")
        stick = (d == "up", d == "down", d == "left", d == "right")
        out += [(stick, d == "fire" or bool(fire))] * int(n)
    return out
