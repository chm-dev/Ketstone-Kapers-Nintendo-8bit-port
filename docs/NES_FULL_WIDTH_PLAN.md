# NES full-width playfield plan (256 px, 1.6x x)

**Status: IMPLEMENTED 2026-11-05 - Stage 1 (BG/renderer/HUD) and Stage 2 (widened sprites + dyn)
are in the build; Stage 3 (hand cleanup + playtest) is open.** Scope is **NES only**;
GBC/DMG stay 160 px, 1:1. Measured results and deviations from this plan: [As built](#as-built-2026-11-05).

Related: `docs/DECISIONS_PENDING.md` W1 (decision), W2-W9 (what was actually done), `docs/PORTING_PLAN.md`,
`HANDOFF.md`.

## Decision

- NES playfield becomes **256x192 at x=0, y=16** (32x24 tile map, 16x12 attribute cells).
- The game/world stays in **160 Atari units**. Engine, timer, thief, obstacle, collision,
  sound and all `tests/golden/*.txt` are untouched.
- The renderer maps world X to screen X:
  `screen_x = ((HPOS - 0x30) * 8) / 5` (use a 160-byte LUT; do not divide on 6502).
  Vertical mapping is unchanged (`FEET_Y0 147`, `FLOOR_DY 32`, `PF_TOP_PX 16`).
- Regenerate the **NES** background tileset/maps from 1.6x horizontally scaled 160 px
  composites, and widen the NES sprite frames to 12-13 px in an **NES-only** data file.
  `src/spr_data.c` stays the 160 px set used by GBC/DMG.
- Keep the current vertical layout: 16 px top, 24 playfield rows (16..207), bottom band
  rows 26-28. The mock's 32 px black top is vertical centring, not a requirement.
- The mock `assets/data/!nes_proposed_viewport.png` is a 1.6x horizontal stretch of the
  160 px screen-0 composite (see [Why 1.6x](#why-16x-not-15x)).

## Why 1.6x, not 1.5x

The mock's geometry matches `x * 1.6`, `y + 31`: floor-1 counter edges are at x
17-22/41-44 and 105-110/129-132 in the 160 px crop and 27-36/65-69 and 167-176/206-209
in the mock; scaled by 1.6 that is 27-35/66-70 and 168-176/206-211. The 181-line
playfield is unchanged vertically.

`256 / 160 = 1.6`; 32 columns and 16 attribute cells fill the screen exactly.

| Playfield | Scale | Tile cols | Bars if centred | 16 px attribute grid | Measured BG tiles/screen |
|---|---|---|---|---|---|
| **256** | **1.6x** | **32** | **0** | **clean** | **145 max** |
| 240 | 1.5x | 30 | 8 + 8 px | **split at both edges** | 149 max |
| 224 | 1.4x | 28 | 16 + 16 px | clean | 144 max |
| 192 | 1.2x | 24 | 32 + 32 px | clean | 136 max |

- 1.5x centred leaves 8 px each side. 8 is not a multiple of the NES 16x16 attribute
  cell, so the first/last cells mix the black margin and the playfield; the current
  margin uses a dedicated solid tile + palette, so this shows as wrong colours at the
  edge. Making the bar 16 px on one side avoids it but is asymmetric.
- 1.5x is **not cheaper**: measured unique BG tiles were 149 max / 1048 total vs 145 /
  1045 at 1.6x. Any non-1:1 resample breaks the original 8 px dedup, so 1.4x (144) and
  1.2x (136) are not materially cheaper either. ROM/screen is ~3.28 KB at both 1.5x and
  1.6x.
- Sprite width is 8x1.5=12 px vs 8x1.6=12.8 (~13 px); both are two 8 px sprite columns
  and use the same OAM.
- If full-bleed edge clipping is rejected after playtest, the clean fallback is **1.4x
  at 224 px with 16 px bars**, not 1.5x.

Probe caveat: the tile counts above came from a 4-restart palette search using the same
crop/cleanup as `tools/gen_bg.py`. The real generator (12 restarts) may differ by a few
tiles; re-measure before fixing `HUD_T0`.

## Target geometry

| Item | Now | Target |
|---|---|---|
| Screen | 256x240 | 256x240 |
| Playfield | 160x192 at x=48, y=16 | 256x192 at x=0, y=16 |
| Map | 20x24 (480 B) | 32x24 (768 B) |
| Attribute map | 10x12 (120 B) | 16x12 (192 B) |
| HUD strip | BG rows 2-3, cols 6-25 | BG rows 2-3, full width |
| Title band | BG rows 26-28 | same, recentred for 32 cols |
| Minimap | baked box x 40..119, y 172..185 | scaled box x ~64..190; recompute markers |
| BG tiles/screen | 60-89 | 88-145 measured |
| Dyn tiles | 6 / 23 / 31 (screens 4/0/7) | ~9 / 35 / 45 estimate (measure) |
| Sprite tiles | 41 | ~65 |
| Sprite hardware/frame | 3 | ~6 |

## Budgets and gates

### CHR (256 BG tiles total, 8 KB CHR-RAM)

Current HUD starts at `$A0` (160) and uses 82 tiles. The 1.6x background uses 128-145
tiles **per screen**, so the HUD must move.

- Move `HUD_T0` to after the measured maximum of `bg_ntiles[s] + dyn_tiles[s]`.
  With the current 82-tile HUD the ceiling is `HUD_T0 <= 174` (`256 - 82`). The
  mechanical 1.6x background + current dyn is 168 worst (screen 0), so there is a
  small margin. If the widened escalator/elevator pushes past 174, free tiles first
  (options below) - do not just overlap the HUD.
- The NES BG and OBJ pattern tables are **independent**: the ROM sets
  `shadow_PPUCTRL = $88` at fixed-bank `0xC435` (`A9 88 85 24 8D 00 20`; BG table
  `$0000`, sprites `$1000`; `set_bkg_data` derives the base from PPUCTRL bit 4,
  `set_sprite_data` from bit 3). BG ids 0-255 can be used freely, and the current
  minimap markers at OBJ `$80-$82` are fine.
- `tools/gen_dyn.py` currently asserts `bg+dyn <= $80` (comment: "shared sprite/HUD
  range"). That limit is over-conservative for the NES; with separate tables the real
  ceiling is `HUD_T0` (and <=256 overall). Raise `TILE_LIMIT` to `HUD_T0` and re-check
  the screens.
- If `bg + dyn + HUD > 256`, pick one:
  1. Clean the stretched art to recover 10-20 tiles (best chance on screens 0-3).
  2. Rebuild the minimap from HUD tiles instead of the baked BG box (frees its BG
     tiles; markers become 1-2 map writes).
  3. Reduce the HUD from 82 to ~42 tiles by sharing one glyph set between the sky text
     and the title band (palette slot reorder so one ink index works in both).
- Add asserts in `gen_dyn.py`/`gen_hud.py`: `bg_ntiles[s] + dyn_tiles[s] <= HUD_T0`
  and `HUD_T0 + HUD_NTILES <= 256`.

### ROM banks (16 KB switchable banks)

Measured estimate for the mechanical 1.6x art:

- Bank 1: screens 0-3 (~12.8 KB) + HUD (~1.3 KB) = ~14.2/16 KB.
- Bank 2: screens 4-7 (~11.6 KB) + dyn data/code (~1.9 KB) = ~13.5/16 KB.

This fits, but there is little room. If native/cleaned art exceeds ~165 BG tiles on any
screen in 0-3, move a screen to bank 3 and update `BG_BANK(s)` + `build.ps1` rather than
squeezing.

### OAM / CPU

Widened actors need ~6 hardware sprites per frame (2 columns x 3 rows) instead of 3.
Worst case (3 radio copies on every floor) is ~87 of 64; current worst is ~45.

- Plan for **8x16 sprite mode** (13x22 actor -> 2x2 = 4 sprites; worst ~59) if GBDK's
  metasprite path supports it, otherwise add a hard OAM cap (~60) and skip extra
  copies.
- Measure the sprite pass in Mesen after widening; the 6502 renderer cost roughly
  doubles.

### Upload time

Per-screen upload grows from ~2.4 KB to ~3.6 KB (CHR + map + attributes). The existing
black flip (`show_screen`, E5) grows by ~1-2 frames. Acceptable; revisit only if it
looks bad.

### Palette

The 1.6x probe's per-cell palette error is essentially unchanged (366-370 vs the
current art). Keep the global 4-palette set for the first pass; per-screen palettes
(B2) remain a separate option if edge colours annoy.

## Implementation order

### As built (2026-11-05)

Stages 1 and 2 were done in one pass (the dyn rebuild belongs to stage 2 but screen 0's escalator is
part of the stage-1 screenshot, so it came first).  Details per item are in `docs/DECISIONS_PENDING.md`.

| Item | Plan estimate | As built |
|---|---|---|
| BG tiles/screen | 88-145 | 145/143/158/144, 86/141/156/115 (max 158) |
| Dyn tiles | ~9/35/45 | 30 (s0), 14 (s4), 41 (s7); totals 175/100/156 |
| Worst BG+dyn | 168 | 175 (screen 0) |
| `HUD_T0` | <= 174 with an 82-tile HUD | **175** with a **64-tile** HUD (37 sky + 25 band glyphs, hat, black); ends at 238 |
| Sprite tiles | ~65 | 152 (13 px wide, deduped with mirrors), OBJ `$A0` kept for markers |
| Sprite hw/frame | ~6 | 6 (2 cols x 3 rows); OAM capped at 64, whole actors skipped |
| ROM banks | 4 x 16 KB | 8 x 16 KB (banks 0,4,5,6 empty): bank 1 bg 0-3+HUD, bank 2 bg 4-7+dyn, bank 3 sprites |
| Flip | +1-2 frames | **7 frames, was 13** (static CHR/palettes moved to `gfx_init`) |
| `gen_dyn.py TILE_LIMIT` | `HUD_T0` | reads `HUD_T0` from `hud_data.h`, asserts `bg+dyn <= HUD_T0` |

Deviations from the stage list:

1. **HUD font** was cut from 82 to 64 tiles instead of moving `HUD_T0` to 174: screen 0 needs 175
   bg+dyn tiles, so 82 could not fit at all.  The NES sky font keeps the canonical 37 glyphs
   (`:` `-` `!` were unused) and the band font only has the 25 glyphs the title strings use
   (remapped at runtime through a 37-byte table).  The GB generators were pinned to the full
   40-glyph order so GBC/DMG keep their font.
2. **OAM**: GBDK's metasprite path has no 8x16 mode, so the plan's second option (a hard cap) is
   in place: `draw()` skips a whole actor when it would cross 64 sprites.  Kop and the thief are
   drawn first (lowest OAM index, so they stay in front).
3. **`PF_LEFT_PX` 48 -> gone** and `OBJ_MIN_X` 0x28 -> **0x30**: without the pillarbox a world x of
   $28-$2F would wrap to the right edge, so actors left of the playfield are hidden (the old build
   hid them by luck of the 48 px offset).
4. **Minimap**: the box is at screen x 64..191 (16 px per cell); the marker formula is
   `64 + 16*(7-screen) + (((X-$2C)*8/5)>>4)`.  (The old formula's base was screen 7's cell, not
   screen 0's, as its comment claimed.)
5. **Static uploads** (HUD tiles/sprites, sprite CHR/palettes) moved out of `show_screen` because
   they never change; this made the flip faster than before despite the bigger map/CHR.

### Stage 1 - BG + renderer + HUD, sprites still 8 px wide

Goal: prove geometry, HUD, CHR budget, flip length against the mock.

1. **`tools/gen_bg.py`**
   - Add a width/mode parameter: load the 160x181 crop, resize x to 256 (nearest),
     pad to 192, tile 32x24.
   - `TW=32`, attribute cells `16x12`; adjust the emit/split for banks.
   - Keep the existing crop/cleanup (`clean()`) before scaling. Re-run the palette
     search; previews 2x.
2. **`src/main.c`**
   - `PF_LEFT_PX 48 -> 0`; use `BG_W` (32); write the map at `(0,2)`; attribute offset
     `3+x -> x`; adjust `hud_static()` attribute range.
   - Add a 160-byte X LUT (fixed bank) and use it in `draw()`; keep the current
     `OBJ_MIN_X`/`OBJ_MAX_X` world-unit culling.
   - Keep vertical constants unchanged.
3. **`tools/gen_hud.py` + `main.c`**
   - Move `HUD_T0` after the measured `bg+dyn` max; raise `gen_dyn.py` `TILE_LIMIT`
     from `$80` to `HUD_T0` (NES BG/OBJ tables are separate).
   - Reposition score/time/level/hats for 32 columns; recentre title text.
   - Recompute the minimap marker formula from the scaled box (16 px per screen
     instead of 10; keep the y formula).
4. **Build + gate**: `.\build.ps1`, CHR/bank asserts, Mesen screenshot at the screen-0
   test state, compare with `assets/data/!nes_proposed_viewport.png`.
   - **Do not proceed to Stage 2 until the Stage 1 screenshot looks right.**

### Stage 2 - widened sprites + dynamic scenery

5. **Sprites**: generate 12-13 px wide frames from the existing 20 shapes (nearest is
   acceptable; hand-clean later if needed). Keep the same pivots.
   - Add a new NES-only file (e.g. `src/nes/spr_data_nes.c`) with the scaled `spr_chr`
     / `spr_frame`; compile it in `build.ps1`. Do **not** change `src/spr_data.c`
     (GBC/DMG + `gen_dmg_assets.py` use it).
   - Update OAM accounting; choose 8x16 mode or the cap.
6. **`tools/gen_dyn.py`**
   - Use the scaled composites; regenerate the escalator phases at 256. The band is
     ~1.6x longer/shallower; expect ~11/22 map entries and more tiles.
   - The 8 px elevator shaft becomes ~13 px and crosses two tile columns. `gen_dyn.py`
     must write partial tiles in both columns (or snap the shaft and accept a 1-2 px
     offset).
   - Assert the tile budget against `HUD_T0`.
7. **Build/test**: goldens, screenshots of escalator phases on screens 0/7 and all
   elevator states on screen 4.

### Stage 3 - art cleanup + playtest

8. Clean the stretched art only where it looks bad (long vertical edges, counter
   windows, skyline). Re-run `gen_bg --emit` -> `gen_hud` -> `gen_dyn --emit`.
9. Run the full NES playtest checklist (below); update `HANDOFF.md`.

## Expected files to touch

- `src/main.c` (renderer, HUD positions, minimap, OAM).
- `tools/gen_bg.py` (width, scaling, maps/attributes, bank split).
- `tools/gen_hud.py` (`HUD_T0`, HUD layout).
- `tools/gen_dyn.py` (scaled escalator/elevator, tile coordinates, budget assert).
- `tools/gen_assets.py` + a new NES-only widened sprite data file.
- `build.ps1` (compile the new sprite file, bank lines, fingerprints).
- Generated: `src/bg_data*`, `src/dyn_data*`, `src/hud_data*`, new NES sprite data.
- **Do not touch**: `src/engine.c`, `src/obstacle.c`, `src/sound*`,
  `src/spr_data.c` (shared with GB), `src/gbc/*`, `src/dmg/*`.
- `src/platform.h` only if a new shared type is unavoidable (prefer not).

## Gotchas

- **Shared sprite data**: `src/spr_data.c` is used by GBC/DMG and baked by
  `gen_dmg_assets.py`; widening it would change those ports. Use an NES-only file.
- **CHR `$8800` sharing is a GBC rule, not an NES one.** On NES the BG table is
  `$0000-$0FFF` and the OBJ table `$1000-$1FFF` (PPUCTRL `$88`); the old
  `gen_dyn.py TILE_LIMIT = $80` is conservative. The real NES limit is 256 BG tiles
  (bg + dyn + HUD) and 256 OBJ tiles (sprites + markers), separately.
- **16 px attribute grid**: 1.6x full width is aligned; do not introduce an 8 px
  offset. `PF_LEFT_PX` must stay a multiple of 16 (0 is).
- **Sprite edge clipping**: without the pillarbox, the PPU clips in whole 8 px columns
  and hides sprites at x>=248. A 12-13 px actor at the wall loses at most one column;
  an 8 px actor would disappear. Keep two-column sprites.
- **Dyn partial tiles**: the elevator door column no longer aligns to one 8 px tile at
  1.6x. The generator must handle two columns. The escalator phase rewrite grows.
- **Flip black length**: +~1 KB upload = +1-2 black frames on screen change (E5).
- **OAM/CPU**: widened sprites roughly double the sprite pass; measure before assuming
  60 fps.
- **Stale generated data**: `build.ps1` checks the `bg_data` fingerprint against
  `dyn_data`; run the regeneration order below.

## Regeneration and build commands

```powershell
python -I tools/gen_bg.py --emit
python -I tools/gen_assets.py --emit      # also writes src/spr_nes.c/.h (NES wide set)
python -I tools/gen_hud.py
python -I tools/gen_dyn.py --emit

.\build.ps1
pwsh tests/run_models.ps1
pwsh tests/run_c_trace.ps1              # Mesen, ~21 s
pwsh tests/run_c_trace.ps1 obst         # obstacle chain

.\build_gbc.ps1                         # proves the shared files; needs the GB data regenerated after
pwsh tests/gb/run_gbc.ps1 tests/gb/smoke_steps.json
.\build_dmg.ps1                         # (gen_gbc_assets.py --emit, gen_dmg_assets.py --emit first)
```

`src/spr_nes.c` is in `build.ps1`'s compile list (`-Wf-bo3`) and excluded from the GB builds;
`src/spr_data.c` is excluded from the NES build.

## Acceptance / playtest checklist (NES full width)

1. All 8 screens fill the width; no black side margins; floors/counters/minimap line up
   with the 1.6x mapping (compare with `assets/data/!nes_proposed_viewport.png` on
   screen 0).
2. Kop/thief/obstacles sit on the correct scaled X; left/right screen wrap still flips
   at the same world X; no sprite popping except the expected edge clipping.
3. Jump (A/B), duck, escalators on screens 0/7, elevator on screen 4 (doors, car,
   vanish/reappear) stay aligned to the scaled art.
4. HUD: score/time/level/hats readable; minimap markers move to the right scaled cells.
5. Title / game over text centred; no overlap with the playfield.
6. Ball and pickups touch at the same feel as before (collisions are still world-unit
   boxes).
7. High level (SELECT 4+): radios/carts/planes; check OAM flicker/popping with 3 copies
   on several floors.
8. Flip: black period acceptable; no CHR/map corruption.
9. Goldens still pass; GBC/DMG ROMs build with their 160 px art unchanged.

## Open decisions for the user

1. **Art**: the raw 1.6x stretch is in the build (fastest, matches the mock). Hand-cleaning the
   256 px screens for crisper edges is Stage 3 (W8).  Verdict after playtest?
2. **Sprites**: widened to 13 px (W5).  If the OAM cap makes copies pop at high levels, the
   alternatives are fewer copies or a smaller actor set (W6).
3. **HUD font**: the trimmed 64-tile set (W4) fits with 17 BG tiles to spare.  One ~40-tile font
   (title band in the sky colour) is still possible if a future change needs the headroom.
4. **Minimap**: still the scaled baked box + 2x2 sprites.  Rebuilding it from HUD tiles would free
   BG tiles and make the markers cheaper; not needed for the current budget.
5. **Vertical framing**: kept at 16 px top / 32 px bottom (the mock's +31 centring is not used).
