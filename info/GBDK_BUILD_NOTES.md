# GBDK-2020 build notes (NES / GBC / DMG)

General toolchain knowledge, distilled from the River Raid port. GBDK v4.5.0 lives in `./gbdk` (gitignored).

## NES (mos6502)
- Compile: `gbdk/bin/lcc.exe -mmos6502:nes -Isrc -Wf--opt-code-size -c`. The short `-mnes` spelling is rejected.
- Link: `-Wm-yoA` (auto-size PRG banks), `-Wl-j` (.noi symbols for emulator tests), `-Wl-m` (.map). Banked modules: `-Wf-bo1`, `-Wf-bo2` at compile time (their public functions are BANKED).
- Output is mapper 30 (UNROM-512), CHR-RAM. GBDK always passes `makenes -a 1`, so `tools/patch_nes_header.py` rewrites byte 6 to vertical mirroring. Change it if the nametable layout needs to differ.
- RAM: GBDK keeps `$0000-$00FF` zero page, `$0100-$01C7` transfer buffer + attribute shadow, `$01C8-$01FF` stack, `$0200-$02FF` OAM shadow; C data starts at `$0300`. `build.ps1` asserts DATA/BSS fit below `$0800`. NES RAM is tiny: keep globals few, put platform-specific ones inside `#ifdef`.
- API: `set_bkg_palette(first, n, const palette_color_t*)` (palette_color_t = NES colour byte), `set_bkg_data`, `set_bkg_tiles`, `set_bkg_attributes`, `DISPLAY_ON/OFF`, `SHOW_BKG`, `vsync()`.
- Build: `.\build.ps1 [-Clean]`; `Makefile` mirrors it. Check `roms/*.map` after link.

## Game Boy (sm83)
- Compile: `lcc -msm83:gb -Isrc` (SDCC sm83). Link: `-Wl-j -Wl-m -Wl-yt0x19 -Wl-yo4` (MBC5, 4 banks). `-DPROF_EXPORT_STATICS` exposes statics to profilers.
- Banking: keep banked modules in a real bank (a single-bank link with BANKED calls jumps into unmapped ROM). The linker may not fail on overflow: check each bank's window in the `.map`.
- Dual DMG/GBC ROM selected at boot (see river-raid `src/platform.h`, `gb_cgb`).

## Shared code
- Include `src/platform.h`, never the SDK header directly; branch on `__SDCC_sm83`. After touching a shared file build every existing target.

## SDCC rules that fail silently
1. Flat static state: globals and fixed arrays, not deep call stacks or pointers to stack locals.
2. ISR handlers stay short; never call a BANKED function from an ISR.
3. Do not keep a block-local value live across a call in a complex function: SDCC can alias it with the callee's state. Use a file-scope `static`.
4. Inline `__asm` goes in its own function (SDCC keeps values in registers across asm blocks). Verify with real pixels, not only raw rows.
5. Profile peaks, not averages; prove an optimisation by diffing output byte for byte against an independent reference.

## Asset tools
`gbdk/bin/png2asset`, `gbdk/bin/gbcompress`; project scripts under `tools/`.
Reference project with full history: `C:\dev\AI\river-raid-port` (`archive/nes`, `archive/gbc`, `archive/dmg`).

## NES gotchas found in Keystone Kapers (2026-11-04)
- `set_bkg_data` takes **Game Boy 2bpp layout** (lo,hi bytes interleaved per row) on NES too; planar 8+8 data comes out scrambled.
- Constant data over ~16 KB overflows the fixed bank into unreachable banks (linker only warns `Write from one bank spans`). Put data in its own file, compile with `-Wf-bo1` (build.ps1 maps file name -> bank), and `SWITCH_ROM(n)` before reading.
- `set_bkg_attribute_xy_nes16x16(cellx, celly, pal)` is the unambiguous attribute call; the packed-block `set_bkg_attributes_nes16x16` stride is unclear.
- Call `set_bkg_palette` after `DISPLAY_OFF` (a call before the first one never reached the PPU).

- NES: at runtime the hardware PPUCTRL can be left in +32 increment mode. Before a direct set_bkg_data with the display off, write PPUCTRL = shadow_PPUCTRL & ~(PPUCTRL_NMI|PPUCTRL_INC32), then restore from shadow_PPUCTRL. Otherwise the CHR lands 32 bytes apart.

## GBC gotchas found in Keystone Kapers (2026-11-05)
- `.\build_gbc.ps1` links with `-Wl-yt0x19 -Wl-yo4 -Wm-yC` (MBC5, CGB-only). Output `.gb` from lcc, renamed to `.gbc` (lcc picks the output type from the extension).
- `palette_color_t` and the palette calls need `<gb/cgb.h>`; `<gb/gb.h>` alone does not declare them (platform.h includes both on sm83).
- Metasprite `props` bits differ: NES `$40` = mirror, GB `$40` = FLIP**Y**, GB mirror = `S_FLIPX` `$20`, GB behind-BG = `$80`. NES-generated metasprites need a remap (main_gbc.c `draw()` does it per tile).
- GBDK's default BG addressing is `$8800` mode: BG ids 0-127 at `$9000`, 128-255 at `$8800` (shared with OBJ 128-255); OBJ 0-127 at `$8000` never collide with BG. Screen tiles in VRAM bank 1 (attribute bit 3) leave bank 0 for the HUD and sprites.
- `set_bkg_data` / `set_bkg_tiles` / `set_bkg_attributes` / `set_win_tiles` wait for VRAM access: usable with the display on (a 95-tile screen rewrite takes ~2-3 frames in double speed). Window attributes: `VBK_REG = VBK_ATTRIBUTES; set_win_tiles(...)`.
- Write CGB palettes in VBlank (right after `vsync()`) or with the display off. To hide a rewrite, black the palettes instead of `DISPLAY_OFF` (LCD off shows white).
- The BG-priority attribute (`$80`) hides sprites only over BG colours 1-3: draw HUD text on colour 1 if sprites must stay behind it.
- GB APU: a volume change (NRx2) only takes effect on a retrigger (NRx4 bit 7); NRx2 = 0 turns the channel's DAC off. Load wave RAM (`AUD3WAVE[]`) with NR30 = 0.
