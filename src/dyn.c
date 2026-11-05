/*
 * dyn.c - animated background scenery (docs/ATARI_RE_SPEC.md 9, Atari AC88-AD99).
 *  - Escalators (screens 0, 7): the Atari's quad-width P2 staircase moves 1 px every 4 frames
 *    (phase ($8F>>2)&3).  gen_dyn.py pre-renders the 4 phases; here only the map entries of the
 *    changed tiles are rewritten (7 tiles on screen 0, 14 on screen 7) when the phase changes.
 *  - Elevator (screen 4): per floor closed / doors moving / open car, from $8E and the car floor
 *    [0,1,2,1][$6B&3], with the AD0F rules: open while $8E is $80..$EF (and $74-$77, which the
 *    block turns into $80), moving doors at the other $70-$7F / $F0-$FF values, closed otherwise
 *    (including the $F4 wait for the thief).  One BG palette is redefined on screen 4 for the
 *    teal car (gen_dyn.py picks the palette that screen never uses).
 * Map writes go through GBDK's VRAM transfer buffer (display on) or straight to the PPU from
 * show_screen (display off).
 */
#include "platform.h"
#include <stdint.h>

#include "bg_data.h"
#include "dyn.h"
#include "dyn_data.h"
#include "engine.h"

#define MAP_X0 6u                   /* BG map position of playfield tile (0,0), see main.c show_screen */
#define MAP_Y0 2u
#define NO_STATE 0xFFu

static uint8_t d_scr;               /* screen the scenery belongs to (set by dyn_screen before any use;
                                     * no initialiser: banked module) */
static uint8_t d_phase;             /* escalator phase drawn */
static uint8_t d_door[3];           /* door state drawn per floor */
static uint8_t d_i, d_n, d_w, d_st, d_e;
static const uint8_t *d_p;
static uint8_t d_pal[4];

/* 0 closed, 1 doors moving, 2 open (car floor only) */
static uint8_t door_state(uint8_t f)
{
    if (car_floor() != f)
        return 0u;
    d_e = elev_8e;
    if ((d_e & 0x7Fu) >= 0x70u) {
        if (((d_e >> 2) & 3u) == 1u)
            return (d_e & 0x80u) ? 0u : 2u;    /* $F4-$F7 depart / wait: closed; $74-$77: opens now */
        return 1u;
    }
    return (d_e & 0x80u) ? 2u : 0u;
}

uint8_t dyn_kop_hidden(void) BANKED
{
    return (uint8_t)(d_scr == 4u && (kop_face & 0xC0u) == 0xC0u && door_state(car_floor()) == 0u);
}

void dyn_load_chr(uint8_t s) BANKED
{
    if (s == 0u)
        set_bkg_data(DYN_T0_0, DYN_N_0, dyn_chr_0);
    else if (s == 4u)
        set_bkg_data(DYN_T0_4, DYN_N_4, dyn_chr_4);
    else if (s == 7u)
        set_bkg_data(DYN_T0_7, DYN_N_7, dyn_chr_7);
}

void dyn_screen(uint8_t s) BANKED
{
    d_scr = s;
    d_phase = NO_STATE;
    d_door[0] = NO_STATE;
    d_door[1] = NO_STATE;
    d_door[2] = NO_STATE;
    if (s == 4u) {
        if (DYN_ELEV_PAL < 4u) {
            for (d_i = 0u; d_i < 4u; d_i++)
                d_pal[d_i] = dyn_elev_pal[d_i];
            set_bkg_palette(DYN_ELEV_PAL & 3u, 1u, d_pal);
            d_p = dyn_elev_cells;
            d_n = *d_p++;
            for (d_i = 0u; d_i < d_n; d_i++, d_p += 2)
                set_bkg_attribute_xy_nes16x16((uint8_t)(MAP_X0 / 2u + d_p[0]), (uint8_t)(MAP_Y0 / 2u + d_p[1]),
                                              DYN_ELEV_PAL & 3u);
        }
        d_p = dyn_s4_fix;
        d_n = *d_p++;
        for (d_i = 0u; d_i < d_n; d_i++, d_p += 3)
            set_bkg_tiles((uint8_t)(MAP_X0 + d_p[0]), (uint8_t)(MAP_Y0 + d_p[1]), 1u, 1u, d_p + 2);
    }
    dyn_update();
}

void dyn_update(void) BANKED
{
    if (d_scr == 0u || d_scr == 7u) {
        d_st = (frame_8f >> 2) & 3u;
        if (d_st == d_phase)
            return;
        d_phase = d_st;
        d_p = (d_scr == 0u) ? dyn_esc_0 : dyn_esc_7;
        d_n = *d_p++;
        for (d_i = 0u; d_i < d_n; d_i++) {
            d_w = d_p[2];
            set_bkg_tiles((uint8_t)(MAP_X0 + d_p[0]), (uint8_t)(MAP_Y0 + d_p[1]), d_w, 1u,
                          d_p + 3u + (uint8_t)(d_phase * d_w));
            d_p += 3u + (uint8_t)(d_w << 2);
        }
    } else if (d_scr == 4u) {
        for (d_i = 0u; d_i < 3u; d_i++) {
            d_st = door_state(d_i);
            if (d_st == d_door[d_i])
                continue;
            d_door[d_i] = d_st;
            set_bkg_tiles(MAP_X0 + DYN_ELEV_TX, (uint8_t)(MAP_Y0 + dyn_elev_ty[d_i]), 1u, 4u,
                          dyn_elev + (uint8_t)(d_i * 12u + d_st * 4u));
        }
    }
}
