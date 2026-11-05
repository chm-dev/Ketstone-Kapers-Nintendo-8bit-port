/*
 * dyn_gbc.c - escalator / elevator scenery for the GBC (rules = src/dyn.c, docs/ATARI_RE_SPEC.md 9).
 * The tiles of every state are in VRAM already (gen_gbc_assets.py fits the palettes to all states):
 * only map tile ids and, on the CGB, attributes change.  DMG (gb_color = 0): src/dmg/dmg_data.h, tile ids
 * only (escalator runs w ids per phase, elevator 4 ids per state).
 */
#include "platform.h"
#include <stdint.h>

#include "engine.h"
#include "gbc_data.h"
#include "dmg_data.h"
#include "dyn_gbc.h"

#define NO_STATE 0xFFu

static uint8_t d_scr = NO_STATE;
static uint8_t d_phase;
static uint8_t d_door[3];
static uint8_t d_i, d_n, d_w, d_st, d_e, d_bank;
static const uint8_t *d_p;
static const uint8_t *d_q;
static const uint8_t *d_esc;

/* 0 closed, 1 doors moving, 2 open (car floor only) - same as dyn.c door_state() */
static uint8_t door_state(uint8_t f)
{
    if (car_floor() != f)
        return 0u;
    d_e = elev_8e;
    if ((d_e & 0x7Fu) >= 0x70u) {
        if (((d_e >> 2) & 3u) == 1u)
            return (d_e & 0x80u) ? 0u : 2u;
        return 1u;
    }
    return (d_e & 0x80u) ? 2u : 0u;
}

uint8_t gdyn_kop_hidden(void)
{
    return (uint8_t)(d_scr == 4u && (kop_face & 0xC0u) == 0xC0u && door_state(car_floor()) == 0u);
}

void gdyn_screen(uint8_t s)
{
    d_scr = s;
    d_bank = gb_color ? gbc_bank[s] : dmg_bank[s];
    d_esc = gb_color ? gbc_esc[s] : dmg_esc[s];
    d_phase = NO_STATE;
    d_door[0] = NO_STATE;
    d_door[1] = NO_STATE;
    d_door[2] = NO_STATE;
    gdyn_update();
}

void gdyn_update(void)
{
    if (d_scr >= 8u)
        return;
    if (d_esc) {
        d_st = (frame_8f >> 2) & 3u;
        if (d_st == d_phase)
            return;
        d_phase = d_st;
        SWITCH_ROM(d_bank);
        d_p = d_esc;
        d_n = *d_p++;
        for (d_i = 0u; d_i < d_n; d_i++) {
            d_w = d_p[2];
            if (gb_color) {                                    /* w ids + w attrs per phase */
                d_q = d_p + 3u + (uint8_t)((uint8_t)(d_phase * d_w) << 1);
                set_bkg_tiles(d_p[0], d_p[1], d_w, 1u, d_q);
                set_bkg_attributes(d_p[0], d_p[1], d_w, 1u, d_q + d_w);
                d_p += 3u + (uint8_t)(d_w << 3);
            } else {                                         /* tile ids only: w per phase */
                d_q = d_p + 3u + (uint8_t)(d_phase * d_w);
                set_bkg_tiles(d_p[0], d_p[1], d_w, 1u, d_q);
                d_p += 3u + (uint8_t)(d_w << 2);
            }
        }
    } else if (d_scr == 4u) {
        for (d_i = 0u; d_i < 3u; d_i++) {
            d_st = door_state(d_i);
            if (d_st == d_door[d_i])
                continue;
            d_door[d_i] = d_st;
            SWITCH_ROM(d_bank);
            if (gb_color) {
                d_q = gbc_elev + (uint8_t)(d_i * 24u + d_st * 8u);
                set_bkg_tiles(GBC_ELEV_TX, gbc_elev_ty[d_i], 1u, 4u, d_q);
                set_bkg_attributes(GBC_ELEV_TX, gbc_elev_ty[d_i], 1u, 4u, d_q + 4u);
            } else {
                d_q = dmg_elev + (uint8_t)(d_i * 12u + d_st * 4u);
                set_bkg_tiles(GBC_ELEV_TX, gbc_elev_ty[d_i], 1u, 4u, d_q);
            }
        }
    }
}
