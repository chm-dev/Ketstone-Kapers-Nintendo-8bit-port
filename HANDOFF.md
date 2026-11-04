# HANDOFF (current status)

**Status 2026-11-04: Phase 1 (RE) mostly done -> start Phase 2 (NES game).**
- Existing NES ROM is only the pipeline proof (`.\build.ps1`, shows raw Atari bitmap tiles, garbled by design). Replace it, do not extend it.
- Phase 2 plan: `docs/PORTING_PLAN.md` section "Phase 2".
- **2026-11-04 end of RE session:** Phase 1 is mostly done. Spec `docs/ATARI_RE_SPEC.md` sections 4-8 (section 8 = status table + open items). Python reference models `tools/kk_model.py` (Kop walk/jump/duck/escalators/elevator, thief, timer) are frame-exact against 8 goldens (`pwsh tests/run_models.ps1`). Data for Phase 2: `assets/data/keystone_data.json` (`tools/extract_data.py`), background composites `assets/atari/runtime/screens/`, sound captures `assets/atari/runtime/sound/`.
- **Open before/during Phase 2 (spec section 8):** obstacle types 6/7/9/10/11 kinematics (probe with `$22` poked), sprite pointer table `$BC9E` + art tile export, collision boxes, difficulty tiers, attract demo, HUD, start/select flow. Start Phase 2 (NES, 160 px pillarbox) with what is verified; fill obstacle details by probing as they are needed.
- Processes: stop `AltirraBridgeServer` and `MesenCE-MCP-Windows` at session end.

- **2026-11-04 Phase 2 step 1 (art) started:** `tools/gen_bg.py` (needs numpy) crops the 8 screen composites to the 160x181 playfield (cols 4..163, lines 23..203, padded to 24 tile rows), searches one global NES-style palette set (bg + 4 triples, 16x16 attribute cells) and writes previews `assets/data/bg_preview_N.png`. Result: looks right, 88-117 unique tiles per screen (fits 256 CHR-RAM, upload per screen). `--emit` now writes `src/bg_data*.c/.h` (data in PRG banks 1/2, `BG_BANK(s)`), and `src/main.c` is a screen viewer (LEFT/RIGHT cycle screens 0-7), rendering checked in Mesen (screen 1 matches the preview; user decided to keep this shared-palette quantisation, may revisit after playtest). Proof data removed. **Not done:** other screens not eyeballed, sprite export (Kop/thief/obstacles), HUD, engine port of `kk_model.py`.

## How to resume (RAM-state mapping)
Tool know-how is in `info/` (see AGENTS.md table); this section is only the project-specific plan.
- Boot -> 320 frames -> START works; level 1 is selected by default. Probes: `tools/atari_snapshot.py` (`--start --frames N --hold right --outdir assets/atari/runtime/<name>`), `tools/atari_coverage.py`.
- Method: snapshot RAM every few frames while holding one input at a time (left, right, up, down, fire); diff zero page `$00-$FF`, `$0100-$01FF`, PMG pages `$0C00-$0FFF` and display-list pointers; correlate with screenshots. Name variables in `tools/symbols.txt`, then `python tools/rdis.py --entry 9F90 --entry 9FB0 --entry 9FD0`.
- Questions to answer: Kop X/floor/jump/duck, scroll (HSCROL shadow, LMS pointers), world width, thief position/speed, timer, score/lives/level (`$03` level BCD), obstacle/object slots and whether they spawn/despawn relative to the view, elevator/escalator state, DLI table inputs (`$70-$79`, `$75,Y`, `$BCAF`).
- Proof-ROM check: start Mesen per `info/MESEN_MCP_NOTES.md` with `roms\keystone_kapers.nes`, then `node tests/nes_shot.mjs build/shot.png 30`.
- Do not read `docs/atari_disasm.txt` whole (2600 lines): grep by address.