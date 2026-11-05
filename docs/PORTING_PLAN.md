# Porting plan

Phases: 0 pipeline proof (done, NES) -> 1 RE spec (display, objects, scroll/floors, collisions, timer, score, sound) -> 2 NES game -> 3 GBC -> 4 DMG.

## Phase 1 RE next steps (in order)
1. Decode DLI `$B200` and PMG use; build a renderer from RAM that matches `screen.png` pixel for pixel (colour bands, sprites). Gives the tile/sprite split and unique-tile counts.
2. RAM map by frame-diffing zero page / `$0100-$01FF` / PMG pages under scripted input: Kop X/floor, scroll, thief, timer, score, obstacle slots.
3. Symbolise `docs/atari_disasm.txt` in `tools/symbols.txt`; write object/collision/timer specs; capture POKEY writes for sound.
4. Python model + golden traces for any procedural logic (as in river-raid).

## Width (REVISED 2026-11-05: NES full width 256 px, 1.6x x)
History: 2026-11-04 chose the 160 px pillarbox first. The RE then showed the world is 8
flip-screens with no smooth scroll (`$2C` wraps at `$2B/$CF`), so "show more world" is not
free. Full width is now a **rendering** change: keep the world/logic at 160 units, map
`screen_x = (HPOS - $30) * 8 / 5`, and regenerate the NES art at 32x24 tiles from 1.6x
horizontally scaled composites. GB/GBC/DMG stay 160 px = 1:1.

1.5x (240 px) was evaluated and rejected: it leaves 8 px bars each side, which splits the
NES 16x16 attribute cells, and it uses slightly *more* BG tiles (149 vs 145 max). 1.4x
(224 px, 16 px bars) is the clean fallback if full-bleed edge clipping is rejected.
Details, budgets, gotchas and the staged order: **`docs/NES_FULL_WIDTH_PLAN.md`**.

## Phase 2 - NES game (full-width 256 px, CHR-RAM, mapper 30)
Read first: `docs/NES_FULL_WIDTH_PLAN.md`, `docs/ATARI_RE_SPEC.md` sections 4-8,
`assets/data/keystone_data.json`, `tools/kk_model.py` (reference logic; port it to C 1:1, then diff C traces against `tests/golden/*.txt`).
1. **Art** (160 px version done; full-width version not started): from `assets/atari/runtime/screens/screen_0..7.png` (336x224 shots, 2 px per colour clock, crop to the 160-px playfield) build per-screen tilemaps + deduped CHR. For full width, scale the cropped 160x181 image to 256x181 first (nearest), then tile 32x24; see the plan doc. Export Kop/thief/obstacle sprites from ROM shapes (`$BB00+{13,47,31,5D,73,89}` Kop; pointer table `$BC9E`, page `$B8` or RAM `$04` for the mirrored set - still to decode) or crop them from screenshots. Write `tools/gen_assets.py` -> `src/*_data.c`; the widened NES sprites go in an NES-only file so `src/spr_data.c` stays the GB set.
2. **Engine in C** (shared, `src/platform.h` only): Kop (walk/jump/duck/escalator/elevator), thief, timer, per-floor object slots, flip-screen scene switching, collisions with bounding boxes, score/lives/bonus, HUD. Keep Atari variable names in comments.
3. **Sound**: BGM from the ROM tables (10 frames/step), effects 1-6 from spec section 7 (NES APU pulse/noise approximations of POKEY values).
4. **Verification**: a debug build that prints/logs the same columns as `tools/atari_trace.py`; compare against goldens (Mesen Lua or MCP memory reads). Playtest checklist for the user at the end of each step.
5. Open RE items (spec section 8) are probed on demand with `tools/atari_trace.py --poke` (set `$22` for higher difficulty, teleport with `$1E/$1D/$2x`). Server start: `info/ALTIRRA_BRIDGE_NOTES.md`.
Then Phase 3 GBC, Phase 4 DMG (same engine, 160x144 viewport).
