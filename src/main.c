/*
 * main.c - Keystone Kapers NES port.
 * Milestone 1: background viewer.  Shows flip-screen N (LEFT/RIGHT cycle through 0..7)
 * from tools/gen_bg.py data, 160 px pillarbox centred.  Replaced by the game engine later.
 */
#include "platform.h"
#include <stdint.h>

#include "bg_data.h"

static void show_screen(uint8_t s)
{
    uint8_t x, y;
    DISPLAY_OFF;
    SWITCH_ROM(BG_BANK(s));
    set_bkg_palette(0u, 4u, bg_pal);
    set_bkg_data(0u, bg_ntiles[s], bg_chr[s]);
    fill_bkg_rect(0u, 0u, 32u, 30u, 0u);                 /* tile 0 = black margin */
    for (y = 0u; y < 15u; y++)
        for (x = 0u; x < 16u; x++)
            set_bkg_attribute_xy_nes16x16(x, y, 1u);
    set_bkg_tiles(6u, 2u, BG_W, BG_H, bg_map[s]);
    for (y = 0u; y < BG_H / 2u; y++)
        for (x = 0u; x < BG_W / 2u; x++)
            set_bkg_attribute_xy_nes16x16(3u + x, 1u + y, bg_attr[s][y * (BG_W / 2u) + x]);
    SHOW_BKG;
    DISPLAY_ON;
}

void main(void)
{
    uint8_t s = 1u, keys, old = 0u;

    show_screen(s);
    for (;;) {
        vsync();
        keys = joypad();
        if ((keys & J_RIGHT) && !(old & J_RIGHT)) { s = (s + 1u) & 7u; show_screen(s); }
        if ((keys & J_LEFT) && !(old & J_LEFT)) { s = (s - 1u) & 7u; show_screen(s); }
        old = keys;
    }
}


