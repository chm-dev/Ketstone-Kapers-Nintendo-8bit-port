# Porting plan

Phases: 0 pipeline proof (done, NES) -> 1 RE spec (display, objects, scroll/floors, collisions, timer, score, sound) -> 2 NES game -> 3 GBC -> 4 DMG.

## Phase 1 RE next steps (in order)
1. Decode DLI `$B200` and PMG use; build a renderer from RAM that matches `screen.png` pixel for pixel (colour bands, sprites). Gives the tile/sprite split and unique-tile counts.
2. RAM map by frame-diffing zero page / `$0100-$01FF` / PMG pages under scripted input: Kop X/floor, scroll, thief, timer, score, obstacle slots.
3. Symbolise `docs/atari_disasm.txt` in `tools/symbols.txt`; write object/collision/timer specs; capture POKEY writes for sound.
4. Python model + golden traces for any procedural logic (as in river-raid).

## Width (DECIDED 2026-11-04: pillarbox first)
Atari playfield 160 colour clocks. GB/GBC/DMG 160 px = 1:1. NES 256 px: (a) pillarbox 160 px centred, (b) widen the store with extra view, (c) 2x horizontal scale (not pixel exact). User chose (a). Revisit a wider NES view once the RE shows whether the world scrolls and whether objects are only active near the view.

## Phase 2 - NES game (160 px pillarbox, CHR-RAM, mapper 30)
Read first: `docs/ATARI_RE_SPEC.md` sections 4-8, `assets/data/keystone_data.json`, `tools/kk_model.py` (reference logic; port it to C 1:1, then diff C traces against `tests/golden/*.txt`).
1. **Art** (not done): from `assets/atari/runtime/screens/screen_0..7.png` (336x224 shots, 2 px per colour clock, crop to the 160-px playfield) build per-screen tilemaps + deduped CHR; export Kop/thief/obstacle sprites from ROM shapes (`$BB00+{13,47,31,5D,73,89}` Kop; pointer table `$BC9E`, page `$B8` or RAM `$04` for the mirrored set - still to decode) or crop them from screenshots. Write `tools/gen_assets.py` -> `src/*_data.c`.
2. **Engine in C** (shared, `src/platform.h` only): Kop (walk/jump/duck/escalator/elevator), thief, timer, per-floor object slots, flip-screen scene switching, collisions with bounding boxes, score/lives/bonus, HUD. Keep Atari variable names in comments.
3. **Sound**: BGM from the ROM tables (10 frames/step), effects 1-6 from spec section 7 (NES APU pulse/noise approximations of POKEY values).
4. **Verification**: a debug build that prints/logs the same columns as `tools/atari_trace.py`; compare against goldens (Mesen Lua or MCP memory reads). Playtest checklist for the user at the end of each step.
5. Open RE items (spec section 8) are probed on demand with `tools/atari_trace.py --poke` (set `$22` for higher difficulty, teleport with `$1E/$1D/$2x`). Server start: `info/ALTIRRA_BRIDGE_NOTES.md`.
Then Phase 3 GBC, Phase 4 DMG (same engine, 160x144 viewport).
