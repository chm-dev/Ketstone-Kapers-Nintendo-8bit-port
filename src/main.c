/*
 * main.c - Keystone Kapers NES port: game loop and renderer.
 * Logic is in engine.c (world coordinates); this file is the camera: flip-screen background
 * (tools/gen_bg.py data, CHR upload per screen) in a 160 px pillarbox centred on the 256 px
 * NES screen, plus PLACEHOLDER sprites for Kop and the thief (solid tiles; real art will come
 * from src/spr_data*).  DEBUG_TRACE builds replay scripted input and log the golden-trace
 * columns (trace.h, tests/run_c_trace.ps1).
 */
#include "platform.h"
#include <stdint.h>

#include "bg_data.h"
#include "engine.h"
#include "trace.h"
#include "sound.h"

/* ---- camera (NES) */
#define PF_LEFT_PX   48u    /* screen px of playfield column 0 (BG drawn from tile column 6) */
#define PF_TOP_PX    16u    /* screen line of playfield line 0 (BG drawn from tile row 2) */
#define OBJ_X_OFS    0x2Fu  /* Atari X ($2C/$1B) whose sprite left edge is playfield px 0 (D5) */
#define FEET_Y0      147u   /* playfield line of the feet on floor 0 at height 0 (D5) */
#define FLOOR_DY     32u    /* $BE50: 62 42 22 02, 32 lines per floor */
#define OBJ_MIN_X    0x28u  /* hide objects left of this (sprite fully in the left margin) */

/* ---- placeholder sprites (D6) */
#define SPR_KOP_HEAD   0u
#define SPR_KOP_BODY   1u
#define SPR_THIEF_HEAD 2u
#define SPR_THIEF_BODY 3u
#define TILE_HEAD    0xFEu
#define TILE_BODY    0xFFu

static const uint8_t ph_tiles[32] = {
    /* 0xFE: colour 2 (GB 2bpp, lo/hi interleaved per row) */
    0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF,
    /* 0xFF: colour 1 */
    0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00,
};
static const palette_color_t spr_pal[8] = {
    0x0Fu, 0x12u, 0x27u, 0x30u,     /* palette 0: Kop (blue body, skin head) */
    0x0Fu, 0x00u, 0x30u, 0x16u,     /* palette 1: thief (grey body, white head) */
};

static uint8_t shown_screen = 0xFFu;
static uint8_t r_x, r_y;

static void show_screen(uint8_t s)
{
    uint8_t x, y;
    vsync();                                 /* let the NMI flush what is already queued */
    DISPLAY_OFF;
#ifdef NINTENDO_NES
    /* No NMI while VRAM is written directly: GBDK's NMI writes the PPU too (attribute
     * flush) and a mid-upload NMI scrambled the CHR of the next screen (D7). */
    PPUCTRL = shadow_PPUCTRL & (uint8_t)~(PPUCTRL_NMI | PPUCTRL_INC32);
#endif
    SWITCH_ROM(BG_BANK(s));
    set_bkg_palette(0u, 4u, bg_pal);
    set_sprite_palette(0u, 2u, spr_pal);
    set_bkg_data(0u, bg_ntiles[s], bg_chr[s]);
    fill_bkg_rect(0u, 0u, 32u, 30u, 0u);                 /* tile 0 = black margin */
    for (y = 0u; y < 15u; y++)
        for (x = 0u; x < 16u; x++)
            set_bkg_attribute_xy_nes16x16(x, y, 1u);
    set_bkg_tiles(6u, 2u, BG_W, BG_H, bg_map[s]);
    for (y = 0u; y < BG_H / 2u; y++)
        for (x = 0u; x < BG_W / 2u; x++)
            set_bkg_attribute_xy_nes16x16(3u + x, 1u + y, bg_attr[s][y * (BG_W / 2u) + x]);
    shown_screen = s;
#ifdef NINTENDO_NES
    PPUCTRL = shadow_PPUCTRL;
#endif
    SHOW_BKG;
    SHOW_SPRITES;
    DISPLAY_ON;
}

/* Place a two-tile (8x16) object: x = Atari X, feet = playfield line of the bottom row. */
static void place(uint8_t head, uint8_t body, uint8_t x, uint8_t feet, uint8_t no_head)
{
    if (x < OBJ_MIN_X) {
        hide_sprite(head);
        hide_sprite(body);
        return;
    }
    r_x = (uint8_t)(x + (PF_LEFT_PX - OBJ_X_OFS));
    r_y = (uint8_t)(PF_TOP_PX + feet - 7u + DEVICE_SPRITE_PX_OFFSET_Y);
    move_sprite(body, r_x, r_y);
    if (no_head)
        hide_sprite(head);
    else
        move_sprite(head, r_x, (uint8_t)(r_y - 8u));
}

static void render(void)
{
    if (kop_screen != shown_screen)
        show_screen(kop_screen & 7u);
    /* Kop: Y = floor line - $1C (bits 5-7 of $1C = floor, bits 0-4 = height above it) */
    place(SPR_KOP_HEAD, SPR_KOP_BODY, KOP_X(), (uint8_t)(FEET_Y0 - kop_c1c), kop_pose == 7u);
    /* thief: visible on any floor of Kop's screen */
    if (thief_screen() == kop_screen && !thief_escaped)
        place(SPR_THIEF_HEAD, SPR_THIEF_BODY, thief_x,
              (uint8_t)(FEET_Y0 - FLOOR_DY * THIEF_FLOOR()), 0u);
    else {
        hide_sprite(SPR_THIEF_HEAD);
        hide_sprite(SPR_THIEF_BODY);
    }
}

static void sound_events(void)
{
    if (eng_events & EV_JUMP)
        snd_play(SND_JUMP);
    else if (eng_events & EV_LAND)
        snd_play(SND_NONE);
    else if (eng_events & EV_STEP)
        snd_play(SND_WALK);
}

#ifndef DEBUG_TRACE
static uint8_t read_input(void)
{
    uint8_t k = joypad(), in = 0u;
    if (k & J_UP)    in |= IN_UP;
    if (k & J_DOWN)  in |= IN_DOWN;
    if (k & J_LEFT)  in |= IN_LEFT;
    if (k & J_RIGHT) in |= IN_RIGHT;
    if (k & (J_A | J_B)) in |= IN_FIRE;
    return in;
}
#endif

static void gfx_init(void)
{
    uint8_t i;
    DISPLAY_OFF;
    SPRITES_8x8;
    set_sprite_data(TILE_HEAD, 2u, ph_tiles);
    set_sprite_tile(SPR_KOP_HEAD, TILE_HEAD);
    set_sprite_tile(SPR_KOP_BODY, TILE_BODY);
    set_sprite_tile(SPR_THIEF_HEAD, TILE_HEAD);
    set_sprite_tile(SPR_THIEF_BODY, TILE_BODY);
    set_sprite_prop(SPR_KOP_HEAD, 0u);
    set_sprite_prop(SPR_KOP_BODY, 0u);
    set_sprite_prop(SPR_THIEF_HEAD, 1u);
    set_sprite_prop(SPR_THIEF_BODY, 1u);
    for (i = 0u; i < 4u; i++)
        hide_sprite(i);
}

void main(void)
{
    gfx_init();
    snd_init();
#ifdef DEBUG_TRACE
    for (;;) {
        engine_init();
        render();
        trace_wait_go();                     /* the tool pokes the scenario start state here */
        while (trace_next()) {
            while (trace_full())
                vsync();
            engine_frame(trace_in);
            trace_emit();
            sound_events();
            render();
            vsync();
            snd_tick();
        }
        trace_finish();
    }
#else
    engine_init();
    snd_bgm(1u);
    for (;;) {
        engine_frame(read_input());
        sound_events();
        render();
        vsync();
        snd_tick();
    }
#endif
}
