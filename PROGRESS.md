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
