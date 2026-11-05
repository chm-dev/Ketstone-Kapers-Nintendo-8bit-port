#ifndef DYN_GBC_H
#define DYN_GBC_H
/*
 * dyn_gbc.h - animated background scenery on the GBC (port of src/dyn.c, same rules):
 * escalator steps on screens 0 and 7 (phase ($8F>>2)&3), elevator doors on screen 4 ($8E, car floor).
 * Data: src/gbc/gbc_data.h (tools/gen_gbc_assets.py), tile ids + CGB attributes per state.
 * Bank-0 code: SWITCH_ROM inside, callers must re-switch before reading banked data afterwards.
 */
#include <stdint.h>

extern uint8_t gb_color;        /* main_gbc.c: 1 = CGB colour path, 0 = DMG shades */

void gdyn_screen(uint8_t s);      /* after the screen's map upload: forget the drawn state, draw the current one */
void gdyn_update(void);           /* every frame: map/attribute writes for changed tiles (VRAM-safe library calls) */
uint8_t gdyn_kop_hidden(void);    /* Kop inside the closed car (Atari ANDs his shape with $97 = 0, A3) */

#endif
