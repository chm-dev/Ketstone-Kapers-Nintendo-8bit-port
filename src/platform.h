#ifndef PLATFORM_H
#define PLATFORM_H

/* One place that picks the GBDK platform header, so shared files build for
 * both targets: SM83 (Game Boy Color, build_gbc.ps1) and 6502 (NES, build.ps1). */
#ifdef __SDCC_sm83
#include <gb/gb.h>
#else
#include <nes/nes.h>
#endif

/* The Game Boy configurations (build_gbc.ps1):
 *   default       PLATFORM_DMG + PLATFORM_DUAL: one ROM, the machine is chosen at boot (PLAN_DMG.md)
 *   -Dmg          PLATFORM_DMG: a DMG-only ROM
 *   -GbcOnly      neither: the original GBC-only ROM, kept for -River2600 and as a reference
 * PLATFORM_DMG means the DMG machinery is compiled (delay queue, sprite sharing, DMG HUD ids).
 * GB_HAS_CGB means the colour machinery is (palettes, VBK, the attribute map).  gb_cgb is 1 on a
 * Game Boy Color: a variable in the dual ROM, a constant in the single-machine ones. */
#if defined(PLATFORM_DUAL) && !defined(PLATFORM_DMG)
#error "PLATFORM_DUAL needs PLATFORM_DMG"
#endif
#ifdef __SDCC_sm83
#if !defined(PLATFORM_DMG) || defined(PLATFORM_DUAL)
#define GB_HAS_CGB
#endif
#ifdef PLATFORM_DUAL
extern uint8_t gb_cgb;
#elif defined(PLATFORM_DMG)
#define gb_cgb 0u
#else
#define gb_cgb 1u
#endif
#endif

#if defined(__SDCC_sm83) && defined(PLATFORM_DMG)
/* Sprite tiles go through the boot-time allocator in gbc/main.c: the ids in the logic stay. */
void dmg_sprite_data(uint8_t first, uint8_t n, const uint8_t *src);
#undef set_sprite_data
#define set_sprite_data dmg_sprite_data
#endif

#endif
