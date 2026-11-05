# GBDK-2020 build notes (NES / GBC / DMG)

General toolchain knowledge, distilled from the River Raid port. GBDK v4.5.0 lives in `./gbdk` (gitignored).

## NES (mos6502)
- Compile: `gbdk/bin/lcc.exe -mmos6502:nes -Isrc -Wf--opt-code-size -c`. The short `-mnes` spelling is rejected.
- Link: `-Wm-yoA` (auto-size PRG banks), `-Wl-j` (.noi symbols for emulator tests), `-Wl-m` (.map). Banked modules: `-Wf-bo1`, `-Wf-bo2` at compile time (their public functions are BANKED).
- Output is mapper 30 (UNROM-512), CHR-RAM. GBDK always passes `makenes -a 1`, so `tools/patch_nes_header.py` rewrites byte 6 to vertical mirroring. Change it if the nametable layout needs to differ.
- RAM: GBDK keeps `$0000-$00FF` zero page, `$0100-$01C7` transfer buffer + attribute shadow, `$01C8-$01FF` stack, `$0200-$02FF` OAM shadow; C data starts at `$0300`. `build.ps1` asserts DATA/BSS fit below `$0800`. NES RAM is tiny: keep globals few, put platform-specific ones inside `#ifdef`.
- API: `set_bkg_palette(first, n, const palette_color_t*)` (palette_color_t = NES colour byte), `set_bkg_data`, `set_bkg_tiles`, `set_bkg_attributes`, `DISPLAY_ON/OFF`, `SHOW_BKG`, `vsync()`.
- Build: `.\build.ps1 [-Clean]`; `Makefile` mirrors it. Check `roms/*.map` after link.
- **Bank count is rounded up (2026-11-05):** with modules in banks 1, 2 and 3 GBDK-2020 links an
  *8*\ x16 KB PRG image (bank 0 and 4-6 empty) instead of 5 banks; the ROM size is not linear in the
  number of banked modules. Fixed bank = the last PRG bank; `-Wf-boN` + `SWITCH_ROM(N)` address bank N.
- **Banked data is only readable with the right bank selected**, including `const` tables read every
  frame (metasprite frames): call `SWITCH_ROM(N)` before the reads (Keystone Kapers does it once at the
  top of its sprite pass). Reading banked data without the switch silently returns another bank's bytes
  (it shows up as wrong sprite palettes, not as a crash).
- `set_bkg_data`/`set_sprite_data` with the display off and NMI off (`PPUCTRL = shadow_PPUCTRL &
  ~(PPUCTRL_NMI|PPUCTRL_INC32)`) is safe; with NMI on, GBDK's handler writes the PPU (attribute flush)
  and scrambles a long CHR upload. Static tiles/palettes can be uploaded once in `gfx_init` instead of
  every screen change (Keystone Kapers: screen flip 13 -> 7 frames).

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
- NES: this ROM boots with `shadow_PPUCTRL = $88` (BG pattern table `$0000`, OBJ table `$1000`). `set_bkg_data` picks the base from bit 4 and `set_sprite_data` from bit 3, so **BG and OBJ tile ids are independent** (256 each). The `gen_dyn.py TILE_LIMIT = $80` comment ("shared sprite/HUD range") is GBC-derived and conservative for NES; the real BG ceiling is 256 total (raise it to `HUD_T0` for the full-width plan).

## GBC gotchas found in Keystone Kapers (2026-11-05)
- `.\build_gbc.ps1` links with `-Wl-yt0x19 -Wl-yo8 -Wm-yc` (MBC5, CGB compatible, one ROM for GBC + DMG; see the DMG section). Output `.gb` from lcc, copied to `.gbc` (lcc picks the output type from the extension).
- `palette_color_t` and the palette calls need `<gb/cgb.h>`; `<gb/gb.h>` alone does not declare them (platform.h includes both on sm83).
- Metasprite `props` bits differ: NES `$40` = mirror, GB `$40` = FLIP**Y**, GB mirror = `S_FLIPX` `$20`, GB behind-BG = `$80`. NES-generated metasprites need a remap (main_gbc.c `draw()` does it per tile).
- GBDK's default BG addressing is `$8800` mode: BG ids 0-127 at `$9000`, 128-255 at `$8800` (shared with OBJ 128-255); OBJ 0-127 at `$8000` never collide with BG. Screen tiles in VRAM bank 1 (attribute bit 3) leave bank 0 for the HUD and sprites.
- `set_bkg_data` / `set_bkg_tiles` / `set_bkg_attributes` / `set_win_tiles` wait for VRAM access: usable with the display on (a 95-tile screen rewrite takes ~2-3 frames in double speed). Window attributes: `VBK_REG = VBK_ATTRIBUTES; set_win_tiles(...)`.
- Write CGB palettes in VBlank (right after `vsync()`) or with the display off. To hide a rewrite, black the palettes instead of `DISPLAY_OFF` (LCD off shows white).
- The BG-priority attribute (`$80`) hides sprites only over BG colours 1-3: draw HUD text on colour 1 if sprites must stay behind it.
- GB APU: a volume change (NRx2) only takes effect on a retrigger (NRx4 bit 7); NRx2 = 0 turns the channel's DAC off. Load wave RAM (`AUD3WAVE[]`) with NR30 = 0.

## DMG gotchas found in Keystone Kapers (2026-11-05)
- **One ROM for both machines (2026-11-05):** `.\build_gbc.ps1` links with `-Wm-yc` (lowercase: header `$0143 = $80`, CGB compatible; `-Wm-yC` = `$C0` CGB only, a plain link = `$00`), MBC5, 8 banks (GBC data banks 1-2, DMG data banks 3-4; MBC5 sizes are powers of two). `main_gbc.c` sets `gb_color = (_cpu == CGB_TYPE)` first thing and branches at runtime; `build_dmg.ps1` only copies the ROM to `.gb`.
- `src/platform.h` (copied from river-raid) already defines a `gb_cgb` macro (`1u` unless `PLATFORM_DMG`/`PLATFORM_DUAL`): a variable named `gb_cgb` fails with "syntax error: token -> '1u'". This project's runtime flag is `gb_color`.
- On a DMG, `VBK_REG` writes are ignored: any attribute write (`set_bkg_attributes`, `set_win_tiles` after `VBK_REG = VBK_ATTRIBUTES`) left on the DMG path lands in the tile map. Gate every VBK/attribute/palette write and `cpu_fast()` on the flag.
- Two generators emitting the same symbol names cannot share one link: the DMG data is `dmg_*` / `DMG_*`; shared constants (`GBC_HT_*`, `GBC_HUD_NTILES`, `GBC_BG_W/H`, `GBC_ELEV_TX`, `gbc_elev_ty`) are asserted equal by `gen_dmg_assets.py`.
- lcc writes `.map`/`.noi` beside the output name, and `.\build.ps1` (NES) owns `roms/keystone_kapers.map/.noi`: the GB build links in `build/gbc` and copies `roms/keystone_kapers_gb.map/.noi` (Gearboy symbol file).
- DMG VRAM = 384 tiles, one bank: OBJ ids 0-127 `$8000`, BG ids 0-127 `$9000`, BG 128-255 `$8800` (shared with OBJ 128-255). The window uses the BG tile set, so HUD + screen tiles share the BG ids (61 + up to 195). A `set_bkg_data` run that crosses id 128 is split into two calls in `show_screen()`.
- No BG flips, no per-tile priority, no per-tile palette: dedupe without flips; sprites keep colours by baking shades into tile pixels (colour 0 stays transparent); BGP/OBP0/OBP1 are global, so a black BGP also blanks the HUD during a screen rewrite.
- A non-CGB ROM in an emulator that has a CGB mode may still run in colour compatibility mode: force DMG (Gearboy `ForceDMG = true`, see tests/gb/run_gbc.ps1 `-Dmg`).
- Same 4 MHz CPU as the GBC's single-speed mode: engine + render still hold 60 fps (checked with `_sys_time` in Gearboy), `cpu_fast()` is GBC-only.
- GB APU (pulse, wave, noise) is identical on DMG; wave RAM must be loaded with NR30 = 0.
