#ifndef DYN_H
#define DYN_H
/*
 * dyn.h - animated background scenery (NES renderer side): escalator steps on screens 0 and 7,
 * elevator doors on screen 4.  Data: src/dyn_data.c (tools/gen_dyn.py).  The engine state it
 * reads: frame_8f (escalator phase ($8F>>2)&3), elev_8e / elev_6b (door state, car floor).
 */
#include "platform.h"
#include <stdint.h>

/* dyn.c lives in PRG bank 2 next to its data (build.ps1 -Wf-bo2): BANKED calls, no SWITCH_ROM inside */
void dyn_load_chr(uint8_t s) BANKED;   /* show_screen, display off, right after the bg CHR upload */
void dyn_screen(uint8_t s) BANKED;     /* show_screen, display off, after the map: palette, overrides, state */
void dyn_update(void) BANKED;          /* every frame after the engine: tile swaps through the VRAM buffer */
uint8_t dyn_kop_hidden(void) BANKED;   /* Kop inside the closed car (Atari ANDs his shape with $97 = 0) */

#endif
