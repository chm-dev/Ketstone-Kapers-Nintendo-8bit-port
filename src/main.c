/*
 * main.c - Keystone Kapers NES port: game loop, state machine and renderer.
 * Logic is in engine.c / obstacle.c (world coordinates); this file is the camera: flip-screen
 * background (tools/gen_bg.py data, CHR upload per screen) in a 160 px pillarbox centred on the
 * 256 px NES screen, sprites from src/spr_data* (tools/gen_assets.py), a bare digit line under
 * the playfield (score, time, lives, level; the real HUD comes later), and sound events.
 * DEBUG_TRACE builds replay scripted input and log the golden-trace columns (trace.h,
 * tests/run_c_trace.ps1).
 */
#include "platform.h"
#include <stdint.h>

#include "bg_data.h"
#include "engine.h"
#include "trace.h"
#include "sound.h"
#include "spr_data.h"

/* ---- camera (NES) */
#define PF_LEFT_PX   48u    /* screen px of playfield column 0 (BG drawn from tile column 6) */
#define PF_TOP_PX    16u    /* screen line of playfield line 0 (BG drawn from tile row 2) */
#define OBJ_X_OFS    0x30u  /* Atari HPOS whose sprite left edge is playfield px 0 (spec 9, G1) */
#define FEET_Y0      147u   /* playfield line of the feet on floor 0 at height 0 */
#define FLOOR_DY     32u    /* $BE50: 62 42 22 02, 32 lines per floor */
#define OBJ_MIN_X    0x28u  /* hide a copy fully left of the playfield ... */
#define OBJ_MAX_X    0xD0u  /* ... or fully right of it */
#define SPR_Y(pf)    ((int16_t)(PF_TOP_PX + (pf) + DEVICE_SPRITE_PX_OFFSET_Y))

/* ---- OAM layout */
#define OAM_KOP      0u     /* 3 */
#define OAM_THIEF    3u     /* 3 */
#define OAM_OBJ      6u     /* up to 4 floors x 3 copies x 2 */

/* ---- bare digit line (row 26, under the playfield) */
#define HUD_ROW      26u
#define HUD_COL      6u
#define HUD_W        20u
#define TILE_DIGIT   0xF0u  /* BG tiles $F0..$F9 = 0..9; tile 0 = black margin */

static const uint8_t digit_rows[10][7] = {
    { 0x70, 0x88, 0x98, 0xA8, 0xC8, 0x88, 0x70 }, { 0x20, 0x60, 0x20, 0x20, 0x20, 0x20, 0x70 },
    { 0x70, 0x88, 0x08, 0x10, 0x20, 0x40, 0xF8 }, { 0xF8, 0x10, 0x20, 0x10, 0x08, 0x88, 0x70 },
    { 0x10, 0x30, 0x50, 0x90, 0xF8, 0x10, 0x10 }, { 0xF8, 0x80, 0xF0, 0x08, 0x08, 0x88, 0x70 },
    { 0x30, 0x40, 0x80, 0xF0, 0x88, 0x88, 0x70 }, { 0xF8, 0x08, 0x10, 0x20, 0x40, 0x40, 0x40 },
    { 0x70, 0x88, 0x88, 0x70, 0x88, 0x88, 0x70 }, { 0x70, 0x88, 0x88, 0x78, 0x08, 0x10, 0x60 },
};

static uint8_t shown_screen = 0xFFu;
static uint8_t oam_used = 40u;
static uint8_t hud_buf[HUD_W];
static uint8_t hud_last[6];
static uint8_t r_i, r_n, r_f, r_o;

static void digit_tiles(void)
{
    uint8_t d, r, t[16];
    for (d = 0u; d < 10u; d++) {
        for (r = 0u; r < 8u; r++) {
            t[r * 2u] = 0xFFu;                                   /* colour 1 or 3: plane 0 set */
            t[r * 2u + 1u] = (r < 7u) ? (uint8_t)~(digit_rows[d][r] >> 1) : 0xFFu;
        }
        set_bkg_data((uint8_t)(TILE_DIGIT + d), 1u, t);
    }
}

static void show_screen(uint8_t s)
{
    uint8_t x, y;
    vsync();                                 /* let the NMI flush what is already queued */
    DISPLAY_OFF;
#ifdef NINTENDO_NES
    /* No NMI while VRAM is written directly: GBDK's NMI writes the PPU too (attribute
     * flush) and a mid-upload NMI scrambled the CHR of the next screen (E5). */
    PPUCTRL = shadow_PPUCTRL & (uint8_t)~(PPUCTRL_NMI | PPUCTRL_INC32);
#endif
    SWITCH_ROM(BG_BANK(s));
    set_bkg_palette(0u, 4u, bg_pal);
    set_sprite_palette(0u, 4u, spr_palettes);
    set_sprite_data(SPR_TILE_BASE, SPR_NTILES, spr_chr);
    set_bkg_data(0u, bg_ntiles[s], bg_chr[s]);
    digit_tiles();
    fill_bkg_rect(0u, 0u, 32u, 30u, 0u);                 /* tile 0 = black margin */
    for (y = 0u; y < 15u; y++)
        for (x = 0u; x < 16u; x++)
            set_bkg_attribute_xy_nes16x16(x, y, 1u);
    set_bkg_tiles(6u, 2u, BG_W, BG_H, bg_map[s]);
    for (y = 0u; y < BG_H / 2u; y++)
        for (x = 0u; x < BG_W / 2u; x++)
            set_bkg_attribute_xy_nes16x16(3u + x, 1u + y, bg_attr[s][y * (BG_W / 2u) + x]);
    shown_screen = s;
    hud_last[0] = 0xFFu;                     /* force a HUD redraw */
#ifdef NINTENDO_NES
    PPUCTRL = shadow_PPUCTRL;
#endif
    SHOW_BKG;
    SHOW_SPRITES;
    DISPLAY_ON;
}

/* ---------------------------------------------------------------- sprites */

static void draw(uint8_t frame, uint8_t flip, uint8_t x, uint8_t pf_y)
{
    if (x < OBJ_MIN_X || x >= OBJ_MAX_X)
        return;
    r_o += move_metasprite_ex(spr_frame[frame][flip ? 1u : 0u], SPR_TILE_BASE, 0u, r_o,
                              (int16_t)(PF_LEFT_PX + (uint8_t)(x - OBJ_X_OFS)), SPR_Y(pf_y));
}

static void render(void)
{
    uint8_t f, fr;
    if (kop_screen != shown_screen)
        show_screen(kop_screen & 7u);
    r_o = OAM_KOP;
    /* Kop: feet = floor line - $1C (bits 5-7 = floor marker, 0-4 = height) */
    draw(spr_kop_pose[kop_pose & 7u], kop_face & 8u, KOP_X(), (uint8_t)(FEET_Y0 - kop_c1c));
    /* thief: on any floor of Kop's screen (the P0 slot copy, types 1-5, is not drawn twice) */
    if (thief_screen() == kop_screen && !thief_escaped)
        draw((uint8_t)(SPR_F_THIEF1 + ((thief_anim - 1u) % 5u)), thief_dir_left(), thief_x,
             (uint8_t)(FEET_Y0 - FLOOR_DY * THIEF_FLOOR()));
    for (f = 0u; f < 4u; f++) {
        if (obj_t[f] < 6u)
            continue;
        fr = obj_frame_of(obj_t[f]);
        if (fr == 0xFFu)
            continue;
        r_n = obj_copies(f);
        for (r_i = 0u; r_i < r_n; r_i++)
            draw(fr, obj_fl[f] & 8u, obj_cx[r_i],
                 (uint8_t)(FEET_Y0 - FLOOR_DY * f + obj_h[f] - 0x1Au));
    }
    if (r_o < oam_used)
        hide_sprites_range(r_o, oam_used);
    oam_used = r_o;
}

/* ---------------------------------------------------------------- bare digit line */

static void put_bcd(uint8_t at, uint8_t v)
{
    hud_buf[at] = (uint8_t)(TILE_DIGIT + (v >> 4));
    hud_buf[at + 1u] = (uint8_t)(TILE_DIGIT + (v & 0x0Fu));
}

/* score 6 digits | time 2 | lives 1 | level 2 (cols 6-11, 13-14, 16, 18-19) */
static void hud(uint8_t lvl)
{
    if (hud_last[0] == score_hi && hud_last[1] == score_lo && hud_last[2] == game_time
            && hud_last[3] == lives && hud_last[4] == lvl)
        return;
    hud_last[0] = score_hi;
    hud_last[1] = score_lo;
    hud_last[2] = game_time;
    hud_last[3] = lives;
    hud_last[4] = lvl;
    for (r_i = 0u; r_i < HUD_W; r_i++)
        hud_buf[r_i] = 0u;
    put_bcd(0u, score_hi);
    put_bcd(2u, score_lo);
    hud_buf[4] = TILE_DIGIT;
    hud_buf[5] = TILE_DIGIT;
    put_bcd(7u, game_time);
    hud_buf[10] = (uint8_t)(TILE_DIGIT + (lives & 0x0Fu));
    put_bcd(12u, (uint8_t)(((lvl / 10u) << 4) | (lvl % 10u)));
    set_bkg_tiles(HUD_COL, HUD_ROW, HUD_W, 1u, hud_buf);
}

/* ---------------------------------------------------------------- sound */

static void sound_events(void)
{
    if (eng_events & EV_MUSIC_OFF)
        snd_bgm(0u);
    if (eng_events & EV_MUSIC_ON) {
        snd_bgm(0u);
        snd_bgm(1u);
    }
    if (eng_events & EV_SFX_END)
        snd_play(SND_NONE);
    if (eng_events & EV_SFX)
        snd_play(eng_sfx);
}

static void gfx_init(void)
{
    DISPLAY_OFF;
    SPRITES_8x8;
    hide_sprites_range(0u, 64u);
    oam_used = 0u;
}

#ifndef DEBUG_TRACE
static uint8_t read_input(uint8_t k)
{
    uint8_t in = 0u;
    if (k & J_UP)    in |= IN_UP;
    if (k & J_DOWN)  in |= IN_DOWN;
    if (k & J_LEFT)  in |= IN_LEFT;
    if (k & J_RIGHT) in |= IN_RIGHT;
    if (k & (J_A | J_B)) in |= IN_FIRE;
    return in;
}

/* states: title (power-on / after a game over; attract demo not ported, G-log) and play */
#define GS_TITLE 0u
#define GS_PLAY  1u
static uint8_t gs, start_sel = 1u, pad, pad_old, lock;
#endif

void main(void)
{
    gfx_init();
    snd_init();
#ifdef DEBUG_TRACE
    for (;;) {
        uint8_t k;
        engine_init();
        render();
        trace_wait_go();                     /* the tool pokes the scenario start state here */
        while (trace_next()) {
            while (trace_full())
                vsync();
            if (dbg_mode == 1u) {            /* obstacle chain (tools/obstacle_model.py replay) */
                snd_id = (trace_in & 4u) ? 5u : 0u;
                play_on = (trace_in & 8u) ? 0xFFu : 0u;
                obj_6e = trace_in >> 4;
                for (k = trace_in & 3u; k; k--) {
                    frame_90++;
                    obj_floor(3u);
                    obj_floor(2u);
                    obj_floor(1u);
                    obj_floor(0u);
                }
                trace_emit();
                continue;
            }
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
    play_on = 0u;                            /* title: frozen level-start scene */
    gs = GS_TITLE;
    for (;;) {
        pad_old = pad;
        pad = joypad();
        if (gs == GS_TITLE) {
            rng_s += 0x3Du;                  /* the moment START is pressed seeds the RNG */
            if (lock)
                lock--;
            else if ((pad & J_SELECT) && !(pad_old & J_SELECT))
                start_sel = (start_sel >= 16u) ? 1u : (uint8_t)(start_sel + 1u);
            else if ((pad & J_START) && !(pad_old & J_START)) {
                game_new(start_sel);
                gs = GS_PLAY;
            }
            eng_events = 0u;
        } else {
            engine_frame(read_input(pad));
            if (game_over) {
                gs = GS_TITLE;
                lock = 120u;                 /* keep the final score on screen a moment */
            }
        }
        sound_events();
        render();
        hud(gs == GS_TITLE ? start_sel : (uint8_t)(level + 1u));
        vsync();
        snd_tick();
    }
#endif
}
