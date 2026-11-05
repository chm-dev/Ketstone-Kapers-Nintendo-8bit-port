# HANDOFF (current status)

**Status 2026-11-05: NES full width (256 px, 1.6x) implemented - stages 1+2 done, playtest pending.**
**GBC/DMG unchanged (160 px); all three ROMs build and the NES goldens/models pass.**
NES, GBC and DMG all feature-complete; none playtested by a human since the full-width change.
Read `docs/DECISIONS_PENDING.md` FIRST: every unattended call/guess (E*, S*, SP*, G*, B*, H*, A*, C*, W*)
with how to revert.

## NES (`.\build.ps1` -> `roms/keystone_kapers.nes`)
Done: Kop/thief/timer engine (frame-exact vs 8 goldens), obstacles (matches obstacle goldens at the Python baseline of 17 torn rows), collisions/lives/score/bonus/pickups, title + game over, real sprites, cleaned backgrounds, HUD + minimap, escalator and elevator animation, APU sound.
Checks: `pwsh tests/run_models.ps1`, `pwsh tests/run_c_trace.ps1` (Mesen, ~21 s; `... obst` for obstacle chain).
Regeneration order after art changes: `gen_bg.py --emit` -> `gen_assets.py --emit` -> `gen_hud.py` -> `gen_dyn.py --emit` (build.ps1 refuses stale dyn data), then the GB pair (`gen_gbc_assets.py --emit`, `gen_dmg_assets.py --emit`) because `spr_palettes`/`bg_pal[0]` feed them.
Not done / approximated: attract demo, long game-over countdown, music restart per life, true pixel collision (box-based), shared 4-palette quantisation artefacts (B2), pickup/hit sounds not captured (S2), Atari font (original 5x7 used), obstacle copy modes 4/6/7 untested, catch/death/radio/bonus only from disassembly (only ball hit has a capture).

**NES full width (2026-11-05, W1-W9):** playfield = 256x192 at x=0,y=16, 32x24 map, 16x12
attributes; world stays 160 units, sprites go through `PF_X[]` (`screen_x = world_x*8/5`).
`gen_bg.py --width 256` (default) stretches the 160 px composites (nearest, src = dst*5/8);
`gen_dyn.py` rebuilds the escalator phases/elevator car in the same space (car = 2 tile columns);
`gen_assets.py --emit` also writes `src/spr_nes.c/.h` (13 px wide frames, 152 tiles, bank 3) which
the NES build uses instead of `src/spr_data.c`. Budgets measured: BG 145/143/158/144/86/141/156/115,
+dyn 30/14/41 -> worst 175; HUD font trimmed to 64 tiles at `HUD_T0 175` (ends 238, 17 spare);
HUD markers at OBJ `$A0`; OAM capped at 64 (whole actors skipped; measured worst 27, theoretical 84).
Screen flip is now 7 frames (was 13: static CHR/palettes moved to `gfx_init`). ROM is 8 banks
(128 KB; banks 0,4,5,6 empty - GBDK rounds the bank count up). Stage 3 (hand-clean the stretched art)
is still open: `docs/NES_FULL_WIDTH_PLAN.md`.

**Hand-editing the NES sprites (W10/W11):** `python -I tools/spr_nes_edit.py --export` writes
`assets/data/spr_nes_edit.png` at 1:1 (transparent background, 20 frames x 2 facings, no grid or
text) plus `.json` layout; `--annotated` gives a 6x reference sheet with the sprite palette of every
8x8 tile. After editing, `python -I tools/spr_nes_edit.py --import` validates each pixel against its
tile's palette, writes `assets/data/spr_nes_overrides.json` and re-emits `src/spr_nes.c/.h`
(then `.\build.ps1`). `gen_assets.py --emit` re-applies the overrides, so hand edits survive
regeneration; `--reset` drops them. An untouched sheet round-trips byte-identically.
The first edit pass (W11) is in: RADIO_A/B, SUITCASE (reshaped handle, 9 px tall) and MONEYBAG,
8 frames in the overrides file; the tile pool is now 172 and the minimap markers moved to OBJ `$C0`.
A frame cannot grow above its top tile row (the suitcase stays 9 px for that reason).

## Playtest checklist (NES)
1. Title: SELECT cycles level 1-16, START begins; ~8 s intro music then Kop moves; time ticks ~every 2 s.
2. Full width: all 8 screens fill 256 px with no black side margins; floors/counters/minimap line up with the art (screen 0 vs `assets/data/!nes_proposed_viewport.png`); HUD reads `SCORE ..` `TIME ..` `LV ..` with hats under SCORE, title text centred in the bottom band.
3. Walk all 8 screens both ways (screen 0 is the right end: hold LEFT to leave it); Kop aligned to floors; sprites 13 px wide (Kop/thief/objects at the same scale as the BG), correct facing, jump (A/B) and duck (down).
4. Escalators on screens 0/7 animate and carry Kop; elevator on screen 4: Up at doors, Kop vanishes while closed, reappears on new floor, Down exits; car/door tiles span two tile columns.
5. Ball on screen 1 bounces; touching = 0.5 s freeze + hit sound, time drains, ball gone. Pickups +200/500/400/1000 by floor.
6. Higher levels (SELECT 4+): radios (jump >=6 px), carts, planes (duck), multiple copies; check for sprite popping when many copies are on screen (OAM cap 64 skips whole actors).
7. Catch thief: +1000, bonus countdown with tick, next level. Time out: death, life lost, restart. Last life: GAME OVER, START restarts. Extra life per 10,000.
8. Thief reaching roof end on floor 3 kills Kop. HUD: score/level/hats/time, minimap markers for Kop/thief/car (16 px per screen, floor 3's marker sits a few px above its stripe - unchanged from the 160 px build).
9. Sound: walk, 18-frame jump, hit, death, pickup, bonus; check by ear (all mappings are estimates, S1/S2).
10. Visual: black/blank flash on screen change (~7 frames), palette artefacts (B2), teal elevator colour, 1.6x pixel doubling on vertical edges (raw stretch, W8).
11. Screen changes: no CHR/map corruption after walking through all 8 screens several times (banked data: bg 1-2, dyn 2, sprites 3).

## GBC / DMG
- GB: `.\build_gbc.ps1` -> `roms/keystone_kapers.gbc`: ONE ROM, header $80: colour on GBC, 4 brighter shades on DMG chosen at boot (`gb_color`); `build_dmg.ps1` just copies it to `roms/keystone_kapers.gb`; symbols `roms/keystone_kapers_gb.noi`. GBC details C1-C8, grey art D1-D5, U1-U3 (`src/gbc/`, `src/dmg/` data banks 3-4).
- Gearboy tests: `pwsh tests/gb/run_gbc.ps1 tests/gb/smoke_steps.json [-Dmg]` (GBC needs `--portable`).
- Playtest GB: black flash on flips (3 frames; DMG flip ~4 frames, HUD included), camera follow, sprite clipping at edges, sound by ear (wave/noise mapping), DMG shade readability (BG_SHADE/SPR_BLACK_SHARE in gen_dmg_assets.py), minimap marker colours. Art regeneration: after gen_bg/gen_assets changes rerun `gen_gbc_assets.py --emit` then `gen_dmg_assets.py --emit` (builds refuse stale data).
- Known duplication: title/play/game-over flow is copied between src/main.c and src/gbc/main_gbc.c (C2) - keep in step.

## Next steps (for the user)
- Playtest the NES full-width build (checklist above), then review docs/DECISIONS_PENDING.md and rework what you dislike (W2-W9, per-screen palettes on NES B2, attract demo, real-capture of pickup/hit sounds S2, catch/death/radio captures).
- Next implementation session: NES Stage 3 - hand-clean the 1.6x art where it looks bad (long vertical edges, counter windows, skyline) and re-run `gen_bg --emit` -> `gen_hud` -> `gen_dyn --emit` (+ the GB pair). Open design questions that stage 3 may answer: raw stretch vs cleaned art, HUD font size, minimap as HUD tiles (`docs/NES_FULL_WIDTH_PLAN.md`, W8).
- Processes: stop AltirraBridgeServer, MesenCE-MCP-Windows, Gearboy at session end; build/*.lock must not linger.
- Do not read docs/atari_disasm.txt whole; grep by address.

- 2026-11-05: NES full width implemented (W1-W9): 32x24 BG at 256 px, 13 px sprites, new HUD layout, 7-frame flip, 128 KB ROM. GBC/DMG rebuilt (only the transparent sprite-palette entry changed). No human playtest yet.
- 2026-11-05: GB camera now shows the skyline from floor 3 (cam_y 31/21/10/0 per floor, V1); DMG lift marker is a black 4x2 bar (V2). Playtest floor-change easing on GB.
- 2026-11-05: NES full-width plan documented (`docs/NES_FULL_WIDTH_PLAN.md`, W1): 256 px = 160-unit world at 1.6x x, new 32x24 NES tileset, NES-only widened sprites; 1.5x rejected (240 px leaves 8 px bars and splits the 16x16 attribute cells; 149 vs 145 max BG tiles). No code/data changed, no ROMs rebuilt.
