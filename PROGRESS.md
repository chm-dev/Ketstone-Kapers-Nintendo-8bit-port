# PROGRESS (append-only)

### 2026-11-04 - Project setup, first RE, NES pipeline proof
- Built workspace from river-raid layout; xex parsed; game = seg 28; VBXE splash ignored; cracker stub named; coverage-driven disassembly (64% code, rest data); display list decoded; NES milestone-0 ROM boots in Mesen and shows live Atari bitmap tiles (170 unique tiles for 20x24; render is not yet correct, see ATARI_RE_SPEC 1).


### 2026-11-04 - Width decision, DLI kernel finding
- User chose 160 px pillarbox for NES. DLI at $B200 is a large per-scanline kernel (WSYNC writes to $D40A in loops, per-line colour and HPOS from tables at $BCAF, $75-$79) that composes floors and sprites; the bitmap alone is not the picture. Plan: reverse game STATE (positions, objects, scroll) and redraw natively on NES/GB instead of replicating the kernel.

### 2026-11-04 - RAM diff probe
- Added tools/atari_ramdiff.py; first input-vs-RAM pass in ATARI_RE_SPEC section 4. Kop X candidate $51/$65. Input is ignored for ~600 frames after START.

- 1-frame probe: $51/$65 are walk-anim shape pointers, Kop position is $2C (+1/frame), $5D coarse. See ATARI_RE_SPEC 4b.
- Traces: world = 8 flip-screens ($1E), Kop X $2C, jump arc table, sound vars $17/. tools/atari_trace.py added. See ATARI_RE_SPEC 4c.
- Disassembly read of main logic; screen composites (tools/atari_screens.py); change-log tool tools/atari_events.py; ATARI_RE_SPEC section 5 (game structure).
- Python models kk_model.py (Kop walk/jump/wrap, thief, timer) frame-exact vs Altirra goldens (tests/); spec section 6; sound logger tools/atari_sound.py.
- Escalators + elevator modelled and frame-exact vs Altirra (tests/test_kk_model.py, tests/test_elevator.py); spec 6b.

### 2026-11-04 (cont.) - Phase 1 RE pass
- Models (kk_model.py): Kop walk/jump/escalators/elevator + thief + timer, all frame-exact vs Altirra (tests/run_models.ps1). Tools: atari_trace/events/sound/lives/screens/ramdiff, dl_dump, extract_data (assets/data/keystone_data.json). Spec sections 4-8.
- Findings: 8 flip-screens, 4 floors, per-floor arrays, hardware-collision driven hits, 4 lives, bonus count, BGM from ROM tables, ball cycle table.

### 2026-11-04 - Phase 2 step 1: backgrounds on NES
- tools/gen_bg.py: 8 screen composites -> one shared 4-palette set (bg + 4 triples, 16x16 attr cells) -> src/bg_data*.c (PRG banks 1/2). main.c = screen viewer, verified in Mesen. Proof ROM data removed. GBDK NES gotchas added to info/GBDK_BUILD_NOTES.md.

## 2026-11-05 unattended orchestration
NES engine port, sprite RE/export, obstacle model+C port, collisions/score/states, sound, bg cleanup, HUD, escalator/elevator animation committed. GBC port started. See HANDOFF.md and docs/DECISIONS_PENDING.md.

## 2026-11-05 GBC and DMG ports done; all three ROMs build. See HANDOFF.md.

## 2026-11-05 NES full-width plan (docs only)
- Decided NES 256 px full width at 1.6x x; world/logic stays 160 units. Plan: `docs/NES_FULL_WIDTH_PLAN.md`; decision/revert: W1. 1.5x rejected (240 px leaves 8 px bars and splits the 16x16 attribute cells). No code/data changed, no ROMs rebuilt.

## 2026-11-05 NES full width implemented (256 px, 1.6x)
- NES playfield is now 256x192 at x=0,y=16: `gen_bg.py --width 256` (32x24 map, 16x12 attrs, src = dst*5/8), renderer maps sprites through a 160-byte `PF_X[]` LUT (`world_x*8/5`). World, engine, goldens untouched.
- `gen_dyn.py` rebuilt at 256 (phases still verified in Atari space): escalator 30/41 tiles, elevator car 12 px = two tile columns (`DYN_ELEV_W 2`, `dyn_elev[72]`); `TILE_LIMIT` is now `HUD_T0`.
- HUD: 32-column layout, font trimmed to 64 tiles (37 sky + 25 band glyphs + hat + black, band remapped through `hud_bmap`), `HUD_T0 175`, ends 238. Minimap 16 px cells, markers re-derived from the scaled box.
- Sprites: new NES-only `src/spr_nes.c/.h` (13 px wide, 152 tiles, bank 3, `SPR_BANK`); `src/spr_data.c` is no longer compiled for NES and stays the GBC/DMG set. OAM capped at 64 (whole actors skipped).
- Static CHR/palettes moved to `gfx_init`: screen flip 7 frames (was 13). ROM now 8 banks (128 KB; 4 empty - GBDK rounding).
- Verified: PPU nametable/attrs/CHR equal the generated data; playfield matches the mock (corr 0.97); models + all 8 goldens pass (obstacle chain at the 17 baseline); GBC/DMG rebuilt (only the transparent sprite-palette entry changed) and both Gearboy smoke runs pass. No human playtest yet; Stage 3 (art cleanup) open. Details: W2-W9 in docs/DECISIONS_PENDING.md.

## 2026-11-05 First hand-corrected sprites imported
- User edited the 1:1 sheet (`assets/data/spr_nes_edit.png`): radio A/B edges, moneybag top/lower rows, suitcase reshaped (bracket handle, 12 px wide, 9 px tall). `tools/spr_nes_edit.py --import` validated every pixel (0 out-of-bounds, 0 off-palette) and wrote `assets/data/spr_nes_overrides.json` (8 frames).
- Editing split shared tiles: 152 -> 172 sprite tiles, so the minimap markers moved to OBJ `$C0` (`gen_hud.py`). Suitcase stays 9 px: the 10th row sat above the frame's tile grid (a third tile row would be a metasprite geometry change, option B chosen).
- Verified: re-export equals the edited PNG pixel for pixel, ROM boots with markers at `$C0-$C2`, models + all 8 goldens pass. W11 in docs/DECISIONS_PENDING.md.

## 2026-11-06 Music no longer stalls on a screen change (S3, all three targets)
- User report: the music jitters/pauses briefly on screen transitions. Cause: `snd_tick()` ran once per main-loop pass, and `show_screen()` blocks its caller during the screen upload, so the sequencer froze mid-note - measured per frame in Mesen/Gearboy by sampling the driver state (`bgm_idx`/`bgm_f`): **9 frozen frames on NES** (`sys_time` only loses 3: it freezes inside the display-off window), **6 on GBC/DMG-in-GBC**.
- Fix: the driver is clocked by the frame interrupt. NES: `snd_start()` = `add_TIM(isr)` + `TMA_REG = TIMER_VBLANK_PARITY_MODE_SYSTEM_60HZ` + `TAC_REG = 0x04` + `set_interrupts(VBL_IFLAG|TIM_IFLAG)` (the emulated timer then overflows exactly once per NMI - one call per frame, no drift). GBC/DMG: `add_VBL(isr)`. `snd_tick`/`eff_load` are `NO_OVERLAY_LOCALS` (6502 ISR rule); `snd_play`/`snd_bgm` set a `busy` flag so the ISR skips one tick instead of reading half-written state.
- NES `show_screen()` keeps the NMI enabled: in GBDK 4.5.0 the NMI early-outs while the display is off (`BIT $2A / BVS`), so it writes no PPU register, still counts frames and still runs the TIM handler; only the +32 increment mode is cleared. The flip looks the same (a few black frames, the game logic still does not advance).
- Verified: per-frame sampling across a flip = 1 tick/frame before, during and after (was 9/6 identical frames); all 8 NES flip screens screenshot clean after 7 flips in row-major walk (no CHR/map damage with the NMI on, E5's diagnosis was wrong for 4.5.0); walk effect + BGM audible in the APU state; models pass, all 8 goldens pass, GBC and -Dmg smoke runs pass. NES 43A12FD5..., GB 5945F732... Not ear-checked by a human.
