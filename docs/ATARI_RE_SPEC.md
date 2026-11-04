# Keystone Kapers (Atari 8-bit) - Reverse-Engineering Specification

Mark each claim **[V]** verified against a live capture or **[H]** hypothesis.

## 0. Source
| Item | Value |
|---|---|
| Input | `xex/Keystone_Kapers.xex`, 98,521 bytes, SHA-256 `3002671416ae613e869753bee14cec6cd5c108ccbcd72478b85ef78131fbc76b` |
| Game image | segment 28, `$9F80-$BFFF` (8,320 bytes) = loader/crack stub `$9F80-$9FFF` + cart-like image `$A000-$BFFF`; RUNAD `$A000`. Saved as `assets/atari/keystone_image_9f80_bfff.bin` |
| Machine | Altirra 800XL NTSC. Boots and plays with this segment alone [V] (RAM `$9F80-$BFFF` after boot == segment 28 byte for byte) |

### Ignored segments [H, strong]
Segments 00-25 (about 70 KB through `$2000-$3FFF` plus `$D65F` writes, seg 00/03/24 are the 6502 stubs) match the **VBXE** register map: `$D640/$D641` core id check (`$10`, `$2x`) -> `$0600`; `$D644-$D648` palette upload (768 B); `$D65E/$D65F` MEMAC window/bank; seg 24 sets XDL, enables video, waits for key/trigger, disables. Without VBXE `$0600=0` and every INIT returns. Not game code.

### Cracker patch [V]
`$9F90/$9FB0/$9FD0`: `PHA; LDA $01; CMP #$9F; BCS skip; PLA; STA ($00),Y; INY|DEX|DEY; JMP back`. Entered from `$A04C`, `$A171`, `$A1E6`; used by init copy loops so the RAM-loaded image is not overwritten.

## 1. Display (first findings)
- Boot state in gameplay [V]: DLIST `$0A00`, CHBASE `$08` (RAM charset at `$0800`, copied from OS font `$E100/$E300` and cart data), PMBASE `$08` (P0-P3 at `$0C00-$0F00`), DMACTL `$3F`, NMIEN `$C0` (VBI `$B0F1`, DLI `$B200`, IRQ `$B578`), HSCROL `7`.
- Display list [V]: 4 blank, mode 6 text line (score/level), then ~150 **mode C** lines (160x1 two-colour, 20 B/line) with many LMS jumps (`$2007`, `$3720`, `$2D6A`, `$2100`...), final mode 6 line `@BA91` with HSCROL (credits / Activision logo). Rows share memory (`$2100` reused) so the store is built from reusable scanline strips.
- **Open:** a naive 20 B/line render of the LMS rows (`tools/render_dl.py`) does not reproduce the screenshot (floors are colour bands from DLI + PMG?). Next: DLI table decode (`$B200`), PMG usage, pixel-match renderer.

## 2. Code map (from coverage)
- Cart code `$A000-$B57F` (~5.3 KB), data `$B580-$BFFF` (2.7 KB: charset parts, DL strips, shape tables). 1277 distinct instruction addresses executed in attract + scripted play. No indirect `JMP (..)` found.
- Reset `$A000`, level init `$A27A/$A292`, main wait `$A2E5`, main body `$A2EB-$AC81`.
- Zero page [H]: `$03` level (BCD), `$22` ?, `$90` frame counter, `$94` VBI sync flag, `$9E` attract flag, `$A1-$A6` timers.

## 3. DLI kernel $B200 [V, structure only]
Per-scanline kernel: STA WSYNC loops, writes COLBK/COLPF/HPOSP per line from tables ($BCAF,X, zero page $70-, $75,Y). It draws floors/sprites, so the mode-C bitmap alone does not reproduce the screen. Strategy: RE game state, redraw natively. Width: pillarbox chosen; still record world width / scroll / object activation range.

## 4. RAM mapping, first pass (tools/atari_ramdiff.py)
Method: boot, START, wait 600 frames (120 is too short: input is ignored during the intro), checkpoint, hold one input for 120 frames, diff `$00-$1FF` every 8 frames.
- `$90`, `$8E`, `$8F`, `$A1`, `$A2`, `$1B`, `$48`, `$63`: change with no input at all = frame counter / timers / thief or obstacle AI. [V, as "input-independent"; meaning H]
- `$51` and `$65` change together, 14 times in 120 frames, range `$31-$89`, only while right/left is held. Candidate Kop X (two copies, e.g. PMG HPOS + logical X). [H]
- Right only: `$0D`, `$12`, `$17`, `$20`, `$2C`, `$5D`, `$6C`. Fire: `$19`, `$1C`, `$53`, `$67`, `$59`, `$51`/`$65` jump to `$13` (jump or being hit?). Up/down alone: no Kop change on this floor (`$2B`, `$5E` are timers). [H]
- Caveat: the left run shows many other changes (`$30-$3A`, `$49-$4D`), so Kop probably met an obstacle or the thief state changed; inputs must be probed at finer resolution (every 1-2 frames) from a fixed checkpoint.

### 4b. 1-frame probe, right held (checkpoint after START+600 frames) [V for observed values, meaning H]
- `$20` = Kop walk-frame index 1..5, +1 every 2 frames, wraps 5->1. `$51`/`$65` = shape-pointer low byte per frame index (`1:$47 2:$31 3:$5D 4:$73 5:$89`), `$65` lags `$51` by 1 frame (double buffer). **Correction: they are not X.** [V]
- `$2C` = Kop position, +1 per frame while right is held (about 1 unit/frame; unit vs pixel unconfirmed). `$5D` = coarse position, +1 per 16 units of `$2C` (`$5D = $95 + ($2C>>4)` observed at `$2C=$80..$A2`). [V]
- `a.pmg()` HPOSP is constant (`$0C $D8 $54 $44`) between frames: the DLI rewrites HPOS per scanline, so Kop X cannot be read from the static register; use `$2C`.

### 4c. World, jump, sound variables (tools/atari_trace.py, per-frame traces) 
- **World = 8 flip-screens** [V]: `$1E` (and `$1D`) = screen index 0..7. Screen 0 is the start screen and the RIGHT end; walking left raises the index. No smooth scroll: when `$2C` crosses `$2B->$CF` the whole scene changes to the next screen (screen 1 shows pillars, screen 0 counters). Kop speed 1 unit/frame both ways [V].
- `$2C` = Kop X within the screen; visible range `$2C..$CB` (160 units, 1 unit = 1 colour clock/px) [H: unit=px]. The wrap jumps by 165 (`$2A->$CF`), so a screen period is probably 165 not 160 [H]. Right wall: screen 0, `$2C=$CA` [V]. Left wall: screen 7, `$2C=$72` [V] (stuck there after ~1300 frames of left). World about 7*160+88 = 1208 px wide [H].
- Jump [V]: starts on fire (also seen on right+up). `$1C & $1F` = jump height (0 on ground), 35-frame arc: `0,1,2,3,4,5,6,7,7,8,8,8,8,9,9,9,9,8,8,8,8,7,7,7,7,6,6,6,6,5,4,3,2,1,0`. Horizontal motion continues in the air at 1/frame. Kop Y shape offset `$67 = $3A - $1C` (`$A846-$A85F`), `$53` = its copy; `$1C` upper bits (>>5) probably floor [H]. `$20` = pose (6 = jumping/standing, 1..5 walk cycle).
- Sound [V]: `$17` = effect id, `$12` = step counter, indexed through `$B8F5,Y` page `$BA`, written to POKEY `$D200`/`$D201` at `$A885-$A89A`; `$17=3` jump (counts down from `$10`), `$17=2` walk step. `$2B` and `$2A` are scratch pointers: do not treat as state.
- Kop is entity X=0; arrays are indexed by X (`$2C,X`, `$67,X`, `$B8D4,X`, `$B9E3,X`): X=1 is probably the thief [H].

## 5. Game structure (disassembly read + traces; tags per line)
**Display**
- Screens are not a clean bitmap. The DL has 152 mode-C rows (LMS strips `$2007`,`$3720`,`$2D6A`,`$2100`x3,`$3000`,`$219D`,`$243F`) and only two DLI flags; the DLI kernel `$B200` draws pillars/escalators/shaft/sprites with PMG data in `$0C00-$0FFF` (the game writes patterns to `$0E60-$0EBF` etc.) plus per-line colours. Rendering from DL memory alone is wrong [V]. **Art plan: per-pixel-mode composites of screenshots** (`tools/atari_screens.py` -> `assets/atari/runtime/screens/screen_0..7.png`, `sheet.png`) for backgrounds, shape tables for sprites.
- 8 screens: 0 = escalator (floor1<->2) + counters, elevator shaft at right edge; 1 = pillars top/bottom, counters mid; 2 = umbrella tables; 3 = pillars; 4 = elevator shaft left, car; 5 = pillars; 6 = umbrella tables; 7 = roof shed, escalators on top floors. 4 floor lines (`BE50`: 62 42 22 02 = Y bases per floor, floor 0 = ground at the bottom). [V from screenshots]
**Game state (zero page)**
| Var | Meaning | Tag |
|---|---|---|
| `$03` | level BCD (1..`$16`, wraps to 1) | V (code `A3AC`) |
| `$22` | difficulty index from level (`$93` copy), drives obstacle types, 0..16 | H |
| `$28` | time left BCD, starts `$50`, -1 every 128 frames (`$90&$7F==0`, `S_AED2` at `A54D`), 0 = time out | V (50->41 over 1130 frames) |
| `$25,$26` | score BCD (`$26` low, `$25` high), `S_AF10` adds A to `$26`; `$21` = lives (max 4, +1 life when `$25` changes) | H |
| `$90` frame counter, `$8E/$8F/$6B` slow counters, `$94` vsync flag, `$A1-$A6` music/timer-bar state | H |
| `$13,$14,$23,$9E` | state flags: `$14` bit7 = playing/active?, `$13` bit7 = bonus countdown, `$23` bit7 = attract/demo, `$9E` = start-press latch | H |
| `$1D` | Kop floor*8 + screen; `$1E` = Kop screen 0..7 (screen 0 right end) | V |
| `$2C+floor` | Kop X per floor (`S_AF51`: X=`$1D>>3`); screen wrap at `$2B`->`$CF` (left) and `$CB`->`$2B` (right, `$1E` 0 excepted) | V |
| `$1C` | bits 0-4 jump height, bits 5-7 used when changing floor | V/H |
| `$1B` | thief X, +1 per 2 frames; `$1F` thief path position 0..`$1F` (bits 3-4 floor, bits 0-2 index along the floor; odd floors run mirrored: `$11 = (low nibble>=8 ? ^$0F : x)` = actual screen); starts `$7A`/`$0B`; when `$1B` passes `$CC` it wraps to `$2B` and `$1F` increments | V |
| `$30+f` | X of the thing on floor f (thief or obstacle) when present on Kop's screen; `$75+f` type/frame; `$34+f` flags (bit3 = direction); `$71+f` height; `$85+f` screen the slot belongs to; `$67+f` Y shape pointer | V for thief case |
| `$75,f` types | 1-5 thief run frames, 6-7 ?, 8, 9, 10-11, 12+ items/obstacles (collision branch `A789-A7F4`: <6 thief catch, +`$10` score; type 6/7 ?, `$B5F7,f` = pickup points per floor `02 05 04 10`) | H |
| `$17,$12` | sound effect id and step; `$B8F5,id` -> table in page `$BA`, `$D200/$D201` | V |
- Thief starts floor 1 (`$1F=$0B`), at screen index 4, moving +X at 0.5 px/frame; reaches Kop's screen after about 1030 frames of idling (screen 0). [V]
- Level init `$A27A`: `$A1..$A5` timer-bar values, `$28=$50`, `$B9BB..` = initial state (`$1B=$7A $1C=0 $1D=0 $1E=0 $1F=$0B $20=$06`), `$2C=$7A`. [V]

## 6. Verified logic (python models: `tools/kk_model.py`; goldens `tests/golden/*.txt`; tests `tests/test_kk_model.py`, `tests/test_thief_model.py`) [V = model == Altirra, frame exact]
**Kop on one floor [V, 705 frames, 2 traces]** (joystick PIA bits active low; `$62` = stick latched at jump start)
- Stick order of priority: down (duck, `$20=7`, no move) > left > right > stand (`$20=6`). Left: `$0C=8`, `x-=1`; right: `$0C=0`, `x+=1`.
- Left limit: `x<=$2A` (`$2D` on screen 7) -> screen 7: `x=$2F` (wall), else `x=$CF`, screen+1 (`$1E++`, `$1D` path +1 on even floors, -1 on odd floors). Right limit: screen 0: `x+1>=$CB` -> `x=$C9` (oscillates `$C9/$CA` while held); other screens: `x+1>=$CC` -> `x=$2B`, screen-1. Wrap frames skip the pose animation.
- Walk pose `$20`: on every step to an odd `x`, `$20 = $20+1`, wrapping 6 -> 1 (so 1..5, one pose per 2 px).
- Jump: trigger (fire) pressed, `$18` latch clear, `$19==0` -> `$19=$12`, `$62`=stick, `$18=$FF` (latch cleared when fire is released). Each following frame: if `$19-6 >= 6` (unsigned wrap: `$19>=12` or `$19<6`) or `$90&3==0` then `$19--`; new `$19>=9` -> `$1C++` else `$1C--`; pose `$20=2`; while `$19>=$10` the stick is re-latched each frame (direction can still change in the first 3 frames); afterwards direction is locked in the air. Max height 9, 35-36 frames depending on `$90&3` phase. Y = `$3A - $1C` (`$67`).
- Walking sound: pose 4 -> `$17=2, $12=2, AUDC1=$08`.
**Thief + timer [V, 3400 frames, floors 1->3]**
- Moves only when `$90` (after the frame's increment) is odd (0.5 px/frame). Direction `$58` bit3 = `(($1F&$18)^8)&8` (odd floors right, even floors left); Kop override on the same floor = flee (`$11 >= Kop screen` -> left else right), Kop on a higher floor = reverse [H, from code `AA06-AA20`, not traced].
- Right overflow `x+1>=$CD`: `x=$2B`, `$1F++` (even-floor override: `$1F--`); left underflow `x-1<$29`: `x=$CF`, `$1F++` on even floors. At a floor boundary (`$1F&7==0` after `++`) `x = ~x + $F8 + 1` = `$CD` (right) so the thief starts the next floor at the same screen end. `$1F==$1F` (roof end) -> `$1A` bit7 = thief escaped [H].
- `$63` anim: `+1` (1..5) on every step to an odd `x`. `$11 = ($1F&$F)>=8 ? ($1F&$F)^$F : $1F&$F`.
- Timer `$28` BCD `-1` when `$90&$7F==1` after the increment (every 128 frames); start `$50`, 49 at the first tick [V].
**Events [V from live traces, tools/atari_events.py / atari_sound.py]**
- Collision flags `$0D+floor` come from GTIA hardware collisions (bit0 hit by ball, bit2 escalator contact); a ball hit freezes Kop ~34 frames and drains the timer 1 unit per 4 frames (time -8..-9); sound id 5.
- Pickup: score `+$B5F7[floor]` hundreds (floor 0 = `02` -> 200 [V]); sound id 4. Thief catch +1000 (`S_AF10` with `$10`) [H].
- Bonus count (after catch, `$13` bit7): every 4 frames `$28--`, score `$26 += 1/2/3` hundreds per unit for `$22 < 8 / < 16 / >= 16` [V for 1], sound id 1 (`AUDF1=$03 AUDC1=$CA`, 1 frame per 4). At `$28 == 0`: `$22++` (level, display = `$22+1`, max 17), `$28=$50`, thief `$1F=$0B`, wait about 120 frames, `$14` = FF. [V]
- Time out (`$28` reaches 0 during play): lose a life, sound id 6 (`AUDF1 $0F,07,03,01`, `AUDC1 $28..$20`), then restart the screen [V for the sound].
- `$03` = start level chosen with SELECT (BCD, 1..`$16`, wraps), `$93` = initial `$22` derived from it; START begins.

### 6b. Escalators and elevator [V: kop_esc*.txt, elev_a/b.txt, frame exact]
- Arrays indexed by floor: `$2C+f` = X on floor f (Kop's X; also the thief's X when the thief is on that floor and Kop's screen). Floor = `$1D>>3`.
- **Escalators** (automatic when walked onto): floor 0 at screen 7 (`$B8D4=$90`, climbs LEFT, `$0C=$A8`), floor 1 at screen 0 (`$65`, climbs RIGHT, `$0C=$80`), floor 2 at screen 7 (`$90`, LEFT). Table `$B9E3 = 07 00 07 E0`. Entry (only when walking, not standing/ducking; skipped if thief path `$1F == $1D`): `h = $1C&$1F` (inverted `~h` when the screen number is odd, i.e. 7), `v = x - (h + base) - 1 (mod 256)` must be 0 or 1 -> `$19=0`, `$18=$FC`, `$1C = ($1C&$FC) | (($8F>>2)&3)`, `x = ((floors 0,2: ~h' + 3) or (floor 1: h')) + base`, `$0C = $B8D7[f]`, pose 6. Ride: only on frames with `$8F&3 == 0` (other frames skip all Kop logic): `x -= 1` (A8) or `+= 1` (80), `$1C += 1`; when `$1C&$1F == 0` (29-32 steps, ~117 frames) `$1D += 1` (next floor), `$0C &= $0F`. While `$1C&$1F >= 13` the next floor's X slot mirrors Kop's X (`A877`).
- **Elevator (screen 4)**: car floor `[0,1,2,1][$6B&3]`. `$8E` counter: +1 per frame, except in the door window `$80..$EF` where it advances only when `($90 & Y) == 0` (Y=7, or Y=1 when Kop is on screen 4 on the car's floor). Wrap `$FF->0` increments `$6B`. While Kop is on screen 4 (block `AD0F`, runs after the sample point): `($8E&$7F)>=$70` and `(($8E&$7F)>>2)&3 == 1`: if `$8E<$80` (`$74-$77`) -> `$8E=$80` (doors open); else (`$F4-$F7`): if the thief's `$1F == $BBA2[$6B&3]` (`0B 14 0B 04`) the car waits (`$8E` held at `$F4`), otherwise `$6B++`, `$8E=0`. Closed phase `$F4 ... $74` is about 120 frames; open phase `$80-$EF` is 112 ticks (896 frames at Y=7, 224 at Y=1).
- Entry: standing still (no left/right/down), up pressed, not jumping, screen 4, door window open (`$8E` in `$80..$EF`), car floor == Kop floor, `$77 <= x <= $79` -> `$1C += 2`, `$0C |= $E0`. Inside every frame: `$1C = car_floor*32 + 2`, `$1D = $BBA1[car_floor] = 04 0B 14 0B`, X copied to the car floor slot; down pressed inside the open window -> `$1C -= 2`, `$0C &= $0F` (out). Kop is carried between floors while the doors are closed.

## 7. Obstacles, collisions, lives, sound, data
**Per-floor object slots** (arrays indexed by floor f, rebuilt on every screen change by `S_AFBB`/`AFC2`): `$75+f` type, `$30+f` X (range `$20..$D9`, wraps), `$34+f` flags (bit3 = direction, bit2 start variant), `$71+f` height (sprite Y offset), `$85+f` screen where floor f's pickup lives (set to the pickup type when collected). Type per (floor f, screen s): screen 0 none; screens with `$85,f == s`: pickup `$0E + (f&1) + carry` (observed `$0F/$10`); else `t = f + (s&3) + 7`, `t >= 11 -> t -= 4` (7..10), floor 3 uses an even/odd remap [H]. Types are then gated by difficulty `$22` through `S_AEEB(A)` (returns carry = `($22&3) >= A or ($22>>2) > 0`): type 7 `A=1` (also removed on screen 4 when `$22<5`), 8 always, 9 `A=2`, 10/11 `A=3`. At level 1 only type 8 (ball) appears [V].
- Pickups (`$85,f` list at level start = 3 random screens from `{1,1,2,3,3,5,6,6}` (`$B9AF`) chosen via frame counters, i.e. pseudo-random; one per floor) [V for level 1: `02 02 02 01`]. Collected: `+B5F7[f]` hundreds (`02 05 04 10`), `$75=2`, `$85,f=type`, sound 4 [V floor 0].
- **Ball** (type 8, level 1): X +1 every 2 frames; height `$71` a fixed 96-frame cycle (table in `assets/data/keystone_data.json`, 18..1B..10 range, repeating exactly) [V].
- **Collision resolution** (`A77A-A841`, hardware collisions in `$0D+f`, mask `$0B`): type 1-5 (thief frames) = catch +`$10` (1000) and `$13 = FF` bonus phase; types 6,7 = hit unless `$1C&$1F >= 6`; 8,9 = hit; 10,11 = death (`$17=6`); `$C..$E` nothing; `>= $F` pickup. **Hit** = `$17=5, $12=8`: Kop frozen 36 frames (9 steps x 4), time drains 1 unit per 4 frames (about -9), AUDF1 `$18`, AUDC1 `$28->$20` [V]. Because contact is detected by hardware sprite overlap, the port needs bounding-box tests: jumping clears a ball by height, ducking (pose 7) clears planes [H].
- **Death** (`$17=6`: time out, plane, thief reached the end `$1F == $1F` with `$1B >= $CD`): AUDF1 `$0F 07 03 01`, AUDC1 `$28..$20`, lasts about 32 frames, then `$21--` and screen restart; thief reset to `$1F=$0B` [V time out, V thief escape].
- **Lives** [V]: `$21` = 3 spare lives at start (3 hats shown), each death `$21--`; death with `$21 == 0` -> game over (`$0B` countdown, 2150 frames, then attract/demo `$23=FF`). Extra life each time the ten-thousands byte `$25` changes (score in hundreds BCD `$25:$26`), max `$21 = 3` [H]. Score overflow sets `$25..$27 = $AA`, ends game [H].
- Bonus after catching: see 6. Level index `$22` 0..16 (display `$22+1`), `$03` start level via SELECT (1..`$16`, 1 = easiest).
**Sound** [V captures in `assets/atari/runtime/sound/*.txt`, tool `tools/atari_sound.py`]
- Effects on channel 1 (`$D200/$D201`): id1 bonus tick AUDF `$03`, AUDC `$CA`, 1 frame / 4; id2 walk step AUDF `$F0`, AUDC `$08` for 1 frame at pose 4; id3 jump AUDC `$A8`, AUDF pattern `$4F,$4F,$4F,$CF` repeating every 4 frames until landing; id4 pickup AUDC `$28` (+decay), AUDF `06 05 03 02 01` stepping every ~4 frames; id5 hit AUDF `$18`, AUDC `$28 -> $20` step every 4 frames; id6 death AUDF `0F 07 03 01`, AUDC `$28 -> $20`. Effect data pages: `$B8F5[id]` -> `$BA00+`, tables dumped in the JSON.
- BGM [V against a 130-frame capture]: ch3 AUDF from `$B700[$A1]`, ch4 AUDF from `$B763[$A1]` (`$A1` steps every 10 frames: `$A2` counts 9..0), ch3 volume `AUDC3 = $A0 | min(2*$A2, 9)`, ch4 AUDC `$A1` constant (distortion 5, vol 1) [AUDC4 `$A5` at level restart], index range 1..`$63` then loops; the whole tune is in `assets/data/keystone_data.json`.
**Assets**: backgrounds `assets/atari/runtime/screens/screen_0..7.png` (+`sheet.png`, `tools/atari_screens.py`), Kop shape bitmaps at `$BB00 + {13,47,31,5D,73,89}` (8 px wide, about 22 rows; 13 = stand, 47/31/5D/73/89 = walk 1/jump/3/4/5, `$BBAD` table) [V pointers, art not yet exported as tiles].

## 8. Phase 1 status (end of session 2026-11-04)
| Area | State |
|---|---|
| World, screens, floors, art composites | done (art tile export pending) |
| Kop walk / jump / duck / escalators / elevator | **frame-exact model** (`tools/kk_model.py`, 7 goldens) |
| Thief path + speed + timer | **frame-exact model** (3400 frames) |
| Collisions, hit/death, lives, game over, bonus, extra life | rules read from code, key values [V] by traces; not yet in a model |
| Obstacles: ball | measured cycle [V]; types 6,7,9,10,11 only from code [H] (appear at higher `$22`; need a probe with `$22` poked) |
| Pickups | rule + level-1 layout [V]; randomisation by frame counters [H] |
| Sound | effects and BGM captured/verified |
| Display kernel | not replicated on purpose (backgrounds from screenshots) |
| Open | per-type obstacle kinematics and sprite pointer table (`$BC9E`), difficulty tiers beyond level 1, thief flee/reverse override trace, attract demo input table (`$B9B7`), HUD layout, SELECT/START screen flow, exact Y of each floor |

## 9. Sprites: shapes, colours, PMG multiplexing (sprite agent, 2026-11-04)
Tools: `tools/atari_sprite_probe.py` (captures: screenshot + RAM `$0000-$0FFF`, runtime dir `assets/atari/runtime/sprites/`, gitignored), `tools/gen_assets.py` (decode + NES export + `--verify`). **[V]** below = matched by `gen_assets.py --verify` over 177 captures (Kop poses, thief on both paths, all obstacle types at `$22` = 3/7/11/15): PMG bytes at the predicted rows 9142/9190 (all misses are one transient frame at a screen change), screenshot pixels with the predicted Atari colour 41815/42741 (misses = sprite overlaps, the escalator rail drawn over the thief on screen 0 floor 1, one-frame lag).

**Players** [V]: single-line PMG at `$0C00` (P0) .. `$0F00` (P3), all normal width during play. P3 = Kop (and the thief when it is on another floor of Kop's screen, screens 1-6). P0 = the floor's object (obstacle, pickup, or the thief on Kop's floor / on screens 0 and 7), P1 = second copy of the same object (same bytes, `AE5E/AE61` write both), P2 = escalator (quad width, `$6D`). The DLI (`B25D-B3EC`) re-positions every player per floor band, top floor first.
- **Coordinates** [V]: HPOS h of a player's left pixel -> playfield x = h - `$30` (screenshot x = 2h - 88); PMG row R -> playfield y = R - 39 (screenshot y = R - 16). Kop HPOS = `$2C+f` directly, objects HPOS = `$30+f`.
- **Shapes are stored bottom row first** [V] (both draw loops write Y=0 at the highest PMG address and `DEX`).
  - Kop pose p (`$20`): shape `$BB00+$BBAD[p]` (`BBAD = 13 47 31 5D 73 89 13 00`: 1-5 walk, 2 doubles as the jump pose, 6 stand, 7 duck = `$BB00`), 25 rows, row Y at R = 188 - 32*floor - h - Y (h = `$1C&$1F`). Row visible only if `$B900[M+Y]` bit0 = 1, M = `$3B` (`$3E` ducking): GTIA ignores colour bit 0, so the colour table doubles as the row mask (`ADE2`).
  - Object type t (`$75+f`): shape `$B800+$BC9E[t]`, `$BBB4[t]+1` rows, row Y at R = `$3E + $BE50[f] + $71[f]` - Y (`AE3E`). `BC9E = 1B 09 1E 35 4C 63 7A 88 01 96 BC C6 B4 B8 D0 9F A9`, `BBB4 = 00 13x5 0C 0C 06 08 08 08 02 02 17 08 09`.
  - Types: 1-5 thief run frames (`$63`), 6/7 radio (2 frames), 8 ball, 9 shopping cart, 10/11 toy plane (2 frames), `$0F` suitcase (floors 0/2), `$10` money bag (floors 1/3). 12/13 (3-row shapes) and 14 (pointer `$D0` runs into table data) are never stored in `$75` by the code [H] and are not exported.
- **Facing** [V]: init (`A17F-A1AA`) copies `$BB00-$BBA0` -> `$0300` and `$B800-$B8CF` -> `$0400` bit-reversed. The high byte picks the set: Kop `$BB`/`$03` by `$89+f` bit3 (= `$0C` bit3, set when walking left); objects and thief `$B8`/`$04` by `$34+f` bit3 (`$58` for the P3 thief). The mirrored copy sits at the same HPOS = an H-flip of the 8 px column. Obstacles with bit3 set move right; the thief moves right with bit3 clear.
- **Colours: one colour per scanline per player from page `$B9`** [V]. COLPM3 = `($67+f),Y` and COLPM0/1 = `($BCAF[t]),Y+1` (one line late through `$11`), Y = band line counter. Net effect per shape row Y (colour stays attached to the body):
  - Kop: `$B900[M-3+Y]` -> `$82` legs/body, `$2A` face/hands, `$00` hat.
  - thief: `$B900[1+Y]` (stripes `$02`/`$0C`, face `$2A/$26/$28`), the same on the P0 and the P3 path.
  - types 8/10/11: `$B900[$BCAF[t]+Y]` (the pointer is moved by `$71`, `B273-B27F`).
  - other objects: `$B900[$BCAF[t]+1+Y]` (their `$71` is fixed at `$1A`).
  - `BCAF = 31 00x5 6B 6B 31 4E 28 28 5A 5A 5A 20 18`.
- **Band artefact** [V]: rows 91-95, 123-127 and 155-159 of P3 are zeroed after drawing (`ADFA`), so the top row of Kop's hat disappears at jump height >= 8. Not worth porting.
- **Copies (`$34&7`, DLI `B2C3-B30F`)** [V for 0/4/6, code for 7]:
  - mode 0: one copy.
  - mode 4: P1 at X+`$40`. When X >= `$A0` it wraps to X-`$81` (bit3 = 0) or X-`$7A` (bit3 = 1).
  - mode 6 (radios, X = `$58`): P1 at X+`$20`, and P0 is re-written mid-line to `$58`/`$98` (`$56` = 0), giving three radios at `$58/$78/$98`.
  - mode 7 (after a radio hit): X and X+`$20`.
  - Other `$34&7` values are not produced.
- **Priority** [code]: PRIOR = `$40+f`, normally 1 (players over playfield). It is 4 (playfield over players) on floors whose background id `$38+f` is 1 or 5 (pillars), set at `AE75`. Seen as `$40 = 01 04 01 01` on screen 3. Player order P0 > P1 > P2 > P3, so an obstacle covers Kop when they overlap.
- **HUD minimap** (`B3EF-B4C6`, bottom band) [code, H]: direct GRAFP writes, not PMG memory.
  - P1 = Kop marker at HPOS `$5D`, colour `$80`, shape `($59)`.
  - P0 = thief marker at `$5E`, colour `$0F`, shape `($5B)` by floor.
  - P2 = escalator marks (`$BAA6`) at `$59`/`$A0`, colour `$C0`.
  - P3 = elevator car at `$7B`, colour `$8A`, shape `($60)` from `$B8D0[$6B&3]`.
  - The marks are 1-2 px; not exported, see DECISIONS SP3.
- **Escalator P2** [code]: diagonal patterns written to `$0E60-$0EBF` on screens 0/7. The 4-phase animation moves P2's HPOS (`$3C-$3E` from `$B8DA/$B8DE[$48]`, `$48 = $B8E2[($8F>>2)&3]`). It is already in the background composites; animate it as BG tiles on the NES.

**NES export** (`python tools/gen_assets.py --emit`):
- `src/spr_data.c/.h`: 20 frames, 41 deduplicated 8x8 tiles (H-flip duplicates merged), 4 sprite palettes (global search over all tiles, YUV distance with chroma x2, Kop/thief weighted; entry 0 = `bg_pal[0]` because `$3F10` mirrors the backdrop). GBDK metasprites, item offsets relative to the previous item (checked with `png2asset`).
- `assets/data/sprites.json`: decoded rows and colours, NES items.
- Previews: `assets/data/sprites_{kop,thief,obstacles}.png` (Atari | NES) and `sprites_chr.png`.
- Pivot = the feet line: Kop y = 147 - 32*floor - h, objects 147 - 32*floor + (`$71`-`$1A`); x = HPOS - `$30`.
- **Scanlines** [V over 177 captures]: worst case 4 NES sprites on a line (Kop + 3 radios, or Kop + 2 copies + 1). Floors never share lines, and Kop's jump (max 9) stays out of the upper band. The 8/line limit is never reached, so no flicker is needed, provided the escalators/elevator stay BG and the minimap gets its own band.

### 9b. Obstacle kinematics (types 6-11) [V: tools/obstacle_model.py vs tests/golden/obst_lv{03,07,0B,0F}.txt]
Goldens: per-frame `$90 $1E $2C $17 $14 $8D $6E $6F $30-$37 $71-$78 $0D-$10`, Kop walking left from screen 0 with `$22` poked after START (`atari_sprite_probe.py --poke 22=NN`), 1140 frames each. The model replays them free-running, re-seeding only on a screen change or a slot rewrite: 9517/9534 floor-frames match.
- 64 samples are "torn": the main loop is not locked to the video frame, so the dump caught the loop halfway through a 3-4 px/frame update. They match again a row later.
- The remaining 17 mismatches are torn samples longer than 3 rows (4 px carts/planes, `$22=$0F`) and 2 ball rows on the first frame after a spawn.
- A screen change costs 2 main loops in one video frame (`$90` += 2). The model steps once per `$90` increment.
Data: `assets/data/obstacles.json` (`python tools/obstacle_model.py --json`), per level `$22` 0..16.

**Gating and tiers.** `S_AEEB(thr)`: enabled if (`$22&3`) >= thr or `$22>>2` > 0. Speed index = `$22>>2`, minus 1 when (`$22&3`) < thr. Thresholds `$BBA2[t]`: radio 1, ball 0, cart 2, plane 3. A gated-off slot becomes `$6E` (0 = empty, X = 1).

**Spawn** (`S_AFBB` at every screen change) [V 55/55 non-random cases; random flips V as observed]:
- Type: screen 0 none; screen == `$85[f]` -> pickup `$0F+(f&1)` at X `$78`; else t = f + (s&3) + 7, t >= 11 -> t-4, floor 3 remapped.
- Flags: `$34` = copy_mode(t, tier) | (`$0C & $0C`). Obstacles start moving in Kop's walking direction: bit3 set (Kop walking left) means they move right.
- tier = 0 if `$22>>2` == 0, else min((`$22>>2`) - ((`$22&3`) < thr), 3). copy_mode = `$BC00+$B8F5[t]` [tier]:
  - radio: `00 04 06 06`
  - ball: `00 00 04 04`
  - cart: `00 00 04 00`
  - plane: `00 00 00 00`
- Start X:
  - moving right: `$39`
  - moving left: `$BA` (`$7C` with 2 copies)
  - radio: `$58` (`$78` when single)
- Random direction (POKEY RANDOM bit3, X = `$7A` when it flips): cart for `$22` in 6..9 or >= 14, plane for `$22` >= 7.
- On screen 4 the radio is removed when `$22` < 5, otherwise forced to mode 4.
- Spawn also resets `$71=$1A`, `$8D=0` and `$90 &= $F3`.

**Motion** (per frame, floors 3..0; nothing moves while `$17` >= 5, i.e. during a hit or death, or while `$14` bit7 is clear):
- Step: +-1 px (bit3 = right). Wrap: x == `$18` -> `$D9`, x >= `$DA` -> `$20`.
- Radio: stationary. Frame = 6 + (code byte `$AAEE[$90>>1]` & 1), pseudo-random flicker.
- Ball: 1 px on odd `$90` (0.5 px/frame).
  - Bounce phase `$8D` is a single global counter, advanced by every ball on screen. It wraps at period = (amp+8)*2; amp = 3 for `$22` < 4 or >= 12, else 12.
  - Each frame: a = (phase - amp) & 255. If a < 16, fold it (a ^= 15 when a >= 8); when `B9A7[a] & $90` != 0 the ball holds (no phase or height change), which slows it near the top.
  - First half of the period: `$71--` (up). Second half: `$71++`.
- Cart: every frame. `$22` >= 14: 4 px; else speed index 1 -> 2 px, otherwise 1 px.
- Plane: `$71=$0A` (flies 16 px above the floor objects), frame `$0A + (($90&2)>>1)`, speed index+1 px/frame (max 4).
- **Radio hit** [code]: only when Kop's jump height is < 6.
  - The hit copy i has `$BEF2[i]`-KopX < `$11` (copies `$98/$78/$58` = bits 0/1/2 of `$6F`). That bit is cleared.
  - After the freeze, `$30 = $BEE9[$6F]` and `$34 = $BEE1[$6F]`, so the remaining radios stay.
