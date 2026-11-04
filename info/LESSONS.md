# LESSONS — detailed rules and recipes (read on demand)

> **Scope note (Keystone Kapers port):** general tool knowledge copied from the River Raid / Robbo projects. Sections titled River-row / Robbo / Worked reference, and paths under `C:\dev\AI\robbo-port2`, are examples from those projects; use this workspace's paths (`./MesenCE-MCP`, `./gearboy`, `./gbdk`) and its own addresses.


Read the section you need, not the whole file. `AGENTS.md` keeps the rules whose violation fails silently.
The NES-specific lessons (Mesen, NES APU, NES frame budget and banking) are in `archive/nes/LESSONS.md`.

## Reverse Engineering Tools

### 1. REA / Ghidra (Static Analysis)
- Load the `$A000–$BFFF` 8 KiB cartridge slice at base address `$A000` (6502 processor).
- Atari hardware register ranges: `GTIA $D000–$D01F`, `POKEY $D200–$D20F`, `PIA $D300–$D303`, `ANTIC $D400–$D40F`.

### 2. AltirraBridge (Dynamic Atari 8-Bit Analysis)
Full reference: `info/ALTIRRA_BRIDGE_NOTES.md`.
- **Server:** `F:\Emu\Atari800\Altirra\AlitrraBridge\AltirraBridgeServer.exe` (note spelling: `AlitrraBridge`).
- **Python SDK:** `F:\Emu\Atari800\Altirra\AlitrraBridge\sdk\python` (`from altirra_bridge import AltirraBridge`).
- **Critical rules:**
  - Always redirect `stdout` and `stderr` to files when starting `AltirraBridgeServer.exe`. An un-drained `stderr=PIPE` hangs the server.
  - Connect via `AltirraBridge.from_token_file(token_path)` from `%TEMP%\altirra-bridge-<pid>.token`.
  - `a.boot(xex)` only arms the loader, and `a.frame(n)` is a **gate** that blocks on the next command. Step `a.frame(240)`–`a.frame(300)` after `boot()` before reading state.
  - Default video mode is `pal`; switch with `a.config("video", "ntsc")` when matching 60 Hz timing.
  - Use `a.peek()` / `a.memdump()` for side-effect-free reads, and `with a.checkpoint():` for non-destructive RAM probing.
  - Clean up server processes (`a.quit()` or `Stop-Process`) and temporary files when done. A prior probe that called `quit()` leaves stale tokens that fail with `WinError 10061`.
- **Breakpoints:**
  - Altirra expression syntax differs from C: equality is `=`, boolean AND is `&`, and memory deref is `db($addr)`. `db(0x...)`, `==` and `&&` are rejected.
  - A conditional breakpoint is the only reliable way to stop on a rare row; keep the condition simple, e.g. `(db($5d)=3)&(db($60)=2)`.
  - **Frame gates coalesce breakpoint hits.** For per-row capture use `a.cycles(2000)` + `a.clock()` and check `regs()["PC"]`.
  - After a breakpoint hit, clear it before stepping off the same PC, otherwise the step retriggers. Re-set it after the step.
  - If using `frame()`, arm the gate **before** `resume()`.
  - `regs()` returns uppercase keys (`PC`, `A`, `X`, `Y`) with `$`-prefixed hex strings.
- **River-row capture recipe:** break at `$AB80` (first instruction after the row renderer). Dump zero page `$00-$FF`, object arrays `$0500-$053F`, and the row at the LMS operand `$3F04/$3F05`; do **not** read zero-page `$04/$05`. Disable object slots (`$4D/$4E`, `$0500-$053F`, Y/status arrays) and centre the jet (`$57`) after each sample so checkpoint resets do not interrupt the trace.
- **Reference implementation:** `tools/river_model.py` is a validated Python translation of the generator; `tools/atari_river_trace.py` captures the per-row trace; `tools/river_validate.py` compares model state and rows against it.

## Porting lessons that carry over

### Lesson 8 — inline asm belongs in its own function
SDCC keeps values in registers across an inline asm block. A `river_fill` asm in the middle of C corrupted island bounds while raw-row tests still passed. Verify with real tile pixels: diff two ROMs with `tests/compare_tile_rows.mjs` and run `tests/host_river.ps1`.

### Lesson 12 — time-based river, 30 Hz logic
The river code must be time-based on `game_ticks`. Game logic runs at 30 Hz and the river at 60 Hz, so the two must agree on elapsed time. `river_scrolled` accumulates until the logic group consumes it, and `river_rows_last` is one frame's share.

### Lesson 14 — profile peaks, not averages
A frame budget missed by one pass costs a duplicate frame. Measure the late passes first (what they contain), then the per-frame and per-function views. Sampler weights are approximate: check a hot spot in more than one view before optimising it.

### Lesson 18 — prove an optimisation by diffing output
Dump what the old and new builds produce and compare them byte for byte, not only with a test. Tests cover what someone thought to check; diffs cover the rest. The reference must be independent of the change: a C rewrite that copied the NES OAM byte order made every GBC enemy invisible, and the assembly written from it matched it perfectly (0 errors). Before a handover, also look at a screenshot.
