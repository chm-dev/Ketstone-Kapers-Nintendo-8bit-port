# AGENTS.md - Keystone Kapers port workspace rules

Stable rules only. Status lives in `HANDOFF.md`; plan in `docs/PORTING_PLAN.md`; history in `PROGRESS.md` (append-only: grep it, do not read it whole).

## Project
Port of the Atari 8-bit **Keystone Kapers** (`xex/Keystone_Kapers.xex`) to **NES, Game Boy Color and DMG**, in C with GBDK-2020 v4.5.0 (`./gbdk`). Same method and tree layout as the sibling project `C:\dev\AI\river-raid-port` (finished; read its `AGENTS.md`, `info/LESSONS.md`, `archive/nes/*` for NES/GB gotchas). NES first, then GBC, then DMG.

## Atari ground truth
- **Game = the 8 KiB image `$9F80-$BFFF`** (xex segments 26-28). Segments 00-25 are a VBXE splash (palette + picture streamed through `$D640-$D65F`, `$0600` = VBXE present flag; every INIT returns at once without VBXE). Ignore them.
- `$9F80-$9FFF` is a **cracker patch**: three stubs make `STA ($00),Y` a no-op when the pointer is in the cart area. Symbols `crack_*` in `tools/symbols.txt`. Do not port them as game behaviour.
- Listing: `docs/atari_disasm.txt` (`python tools/rdis.py`, recursive descent + executed-PC coverage from `tools/atari_coverage.py`). Names go in `tools/symbols.txt`. RE findings go in `docs/ATARI_RE_SPEC.md`; mark each claim *verified* (matched against a live capture) or *hypothesis*.
- Emulator for dynamic analysis: AltirraBridge, `F:\Emu\Atari800\Altirra\AlitrraBridge\` (spelling!). Rules: `info/ALTIRRA_BRIDGE_NOTES.md`, `info/LESSONS.md` of river-raid. Always redirect the server's stdout/stderr to files; stop it at session end. River Raid addresses in copied probes are meaningless here.
- Sound values come from live captures (POKEY trace), not estimates.

## Toolchain
- NES: `.\build.ps1` -> `roms/keystone_kapers.nes` (GBDK `-mmos6502:nes`, mapper 30 UNROM-512, CHR-RAM; `tools/patch_nes_header.py` forces vertical mirroring - revisit if the final design needs another layout). NES RAM is tiny: keep platform-specific globals inside `#ifdef`.
- Shared sources include `src/platform.h`, never `<nes/nes.h>` / `<gb/gb.h>` directly. After touching shared files build every target that exists.
- GBC: `.\build_gbc.ps1` -> `roms/keystone_kapers.gbc` (code in `src/gbc/`, Gearboy tests `tests/gb/`, needs `--portable`). DMG: `.\build_dmg.ps1` -> `roms/keystone_kapers.gb` (same ROM as GBC; build_dmg.ps1 = copy).
- Emulators: MesenCE-MCP (`./MesenCE-MCP`, notes `info/MESEN_MCP_NOTES.md`, client `tests/mcp_client.mjs`, screenshot `node tests/nes_shot.mjs`), Gearboy (`./gearboy`). `gbdk/`, `gearboy/`, `MesenCE-MCP/`, `xex/` are gitignored local tools.

## Tool docs (`info/`, read only the one you need in this session)
| Doc | Read when |
|---|---|
| `info/ALTIRRA_BRIDGE_NOTES.md` | Probing the Atari game (server start, token, frame gates, breakpoints, profiler, memory). |
| `info/MESEN_MCP_NOTES.md` | Running/testing NES ROMs in Mesen (start, MCP tools, screenshots, memory, Lua). |
| `info/GBDK_BUILD_NOTES.md` | Building NES/GB ROMs, GBDK flags, RAM layout, SDCC pitfalls. |
| `info/GEARBOY_NOTES.md` | Running/testing GB/GBC ROMs. |
| `info/LESSONS.md` | RE tool rules and porting lessons. |
Index: `info/README.md`. General tool knowledge goes in `info/`, project status in `HANDOFF.md`/`docs/`.

## Workflow
- **The user runs playtests.** Build the ROM, hand over a checklist; do not drive the emulator to confirm gameplay.
- **No git commits (user rule from river-raid, assumed here):** do not run `git init/add/commit/push` without asking. This folder is not a repo yet.
- Session end: summarize what changed, which ROMs were rebuilt, and update `HANDOFF.md`.
- **Width decision (user, 2026-11-05): NES is 256 px full width, 1.6x horizontal** of the 160-unit world (world/logic stays 160 units; renderer maps `screen_x=(HPOS-$30)*8/5`; see `docs/NES_FULL_WIDTH_PLAN.md`). GBC/DMG stay 160 px 1:1. The 2026-11-04 160 px pillarbox was the first stage (see `docs/PORTING_PLAN.md`).
