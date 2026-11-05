/*
 * main.c - Keystone Kapers NES port: game loop, state machine and renderer.
 * Logic is in engine.c / obstacle.c (world coordinates); this file is the camera: flip-screen
 * background (tools/gen_bg.py data, CHR upload per screen) stretched to the full 256 px NES
 * width (16/10 horizontally, docs/NES_FULL_WIDTH_PLAN.md), sprites from src/spr_data*
 * (tools/gen_assets.py), the HUD in the sky strip + title band, and sound events.
 * The world stays in Atari units (160 x 192 px), so sprite X is mapped through PF_X[]:
 * screen_x = world_x * 8 / 5 (W1 in docs/DECISIONS_PENDING.md); vertical mapping is 1:1.
 * Animated scenery (escalator steps, elevator doors) is dyn.c (banked), driven from render().
 * DEBUG_TRACE builds replay scripted input and log the golden-trace columns (trace.h,
 * tests/run_c_trace.ps1).
 */
#include "platform.h"
#include <stdint.h>

#include "bg_data.h"
#include "dyn.h"
#include "engine.h"
#include "hud_data.h"
#include "trace.h"
#include "sound.h"
#include "spr_nes.h"     /* NES-only 13 px widened frames (src/spr_data.c is the GBC/DMG set) */

/* ---- camera (NES): playfield = 256x192 at x=0, y=16 (32x24 map at tile 0,2) */
#define PF_TOP_PX    16u    /* screen line of playfield line 0 (BG drawn from tile row 2) */
#define OBJ_X_OFS    0x30u  /* Atari HPOS whose sprite left edge is playfield px 0 (spec 9, G1) */
#define FEET_Y0      147u   /* playfield line of the feet on floor 0 at height 0 */
#define FLOOR_DY     32u    /* $BE50: 62 42 22 02, 32 lines per floor */
#define OBJ_MIN_X    0x30u  /* hide a copy fully left of the playfield (no pillarbox to hide it in) */
#define OBJ_MAX_X    0xD0u  /* ... or fully right of it */
#define SPR_Y(pf)    ((int16_t)(PF_TOP_PX + (pf) + DEVICE_SPRITE_PX_OFFSET_Y))

/* world x 0..159 -> playfield px (8/5).  A LUT because the 6502 has no divide. */
static const uint8_t PF_X[160] = {
      0,   1,   3,   4,   6,   8,   9,  11,  12,  14,
     16,  17,  19,  20,  22,  24,  25,  27,  28,  30,
     32,  33,  35,  36,  38,  40,  41,  43,  44,  46,
     48,  49,  51,  52,  54,  56,  57,  59,  60,  62,
     64,  65,  67,  68,  70,  72,  73,  75,  76,  78,
     80,  81,  83,  84,  86,  88,  89,  91,  92,  94,
     96,  97,  99, 100, 102, 104, 105, 107, 108, 110,
    112, 113, 115, 116, 118, 120, 121, 123, 124, 126,
    128, 129, 131, 132, 134, 136, 137, 139, 140, 142,
    144, 145, 147, 148, 150, 152, 153, 155, 156, 158,
    160, 161, 163, 164, 166, 168, 169, 171, 172, 174,
    176, 177, 179, 180, 182, 184, 185, 187, 188, 190,
    192, 193, 195, 196, 198, 200, 201, 203, 204, 206,
    208, 209, 211, 212, 214, 216, 217, 219, 220, 222,
    224, 225, 227, 228, 230, 232, 233, 235, 236, 238,
    240, 241, 243, 244, 246, 248, 249, 251, 252, 254,
};

/* ---- OAM layout */
#define OAM_KOP      0u     /* 2 cols x 3 rows */
#define OAM_THIEF    6u     /* 2 x 3 */
#define OAM_OBJ      12u    /* up to 4 floors x 3 copies x 6, capped at OAM_LIMIT */
#define OAM_LIMIT    64u    /* hardware sprites per frame; a whole actor is skipped when it does not fit */
#define OAM_HUD      60u    /* 3 marker sprites: Kop, thief, elevator car */

/* ---- HUD: score/lives/time/level in the sky strip (BG rows 2-3, dark font on the sky),
 *      title text in the bottom band (BG rows 26-28, bright font on the black margin).
 *      Tiles: src/hud_data.c (tools/gen_hud.py), uploaded in show_screen(). */
#define BAND_ROW     26u
/* minimap = the box baked into the BG (playfield x 40..119 -> screen x 64..191, y 172..185):
 * 16 px per screen, screen 7 at the left end (x 64) and screen 0 at the right end (x 176),
 * floor lines every 4 lines from 172 (floor 3) */
#define MAP_X0       64u    /* screen x of screen 7's minimap cell */
#define MAP_Y_TOP    172u
#define MAP_CELL_W   16u
#define SKY_SPACE    (HT_FONT_S + 36u)
static uint8_t shown_screen = 0xFFu;
static uint8_t oam_used = 40u;
static uint8_t hud_buf[16];
static uint8_t hud_last[5];
static uint8_t band_mode;           /* 0 playfield, 1 title text */
static uint8_t title_msg;           /* 0 power-on, 1 game over */
static uint8_t r_i, r_n, r_f, r_o;

/* font tile of an ASCII char.  Canonical index: 0-9 = '0'-'9', 10-35 = 'A'-'Z', 36 = space;
 * the sky font is emitted in that order, the band font only has the glyphs the title strings use
 * (map = hud_bmap, src/hud_data.c, needs SWITCH_ROM(HUD_BANK) first). */
static uint8_t ch_tile(char c, uint8_t base, const uint8_t *map)
{
    uint8_t i;
    if (c >= '0' && c <= '9')
        i = (uint8_t)(c - '0');
    else if (c >= 'A' && c <= 'Z')
        i = (uint8_t)(10u + (uint8_t)(c - 'A'));
    else
        i = 36u;
    return (uint8_t)(base + (map ? map[i] : i));
}

static void put_text(uint8_t x, uint8_t y, const char *s, uint8_t base, const uint8_t *map)
{
    for (r_n = 0u; s[r_n]; r_n++)
        hud_buf[r_n] = ch_tile(s[r_n], base, map);
    set_bkg_tiles(x, y, r_n, 1u, hud_buf);
}

static void put_bcd(uint8_t x, uint8_t y, uint8_t v, uint8_t base, const uint8_t *map)
{
    hud_buf[0] = ch_tile((char)('0' + (v >> 4)), base, map);
    hud_buf[1] = ch_tile((char)('0' + (v & 0x0Fu)), base, map);
    set_bkg_tiles(x, y, 2u, 1u, hud_buf);
}

/* labels of the sky strip and the bottom band (title text; blank while playing) */
static void hud_static(void)
{
    uint8_t c;
    put_text(2u, 2u, "SCORE", HT_FONT_S, 0);
    put_text(16u, 2u, "TIME", HT_FONT_S, 0);
    put_text(25u, 2u, "LV", HT_FONT_S, 0);
    for (c = 0u; c < 16u; c++)                           /* sky strip palette: tools/gen_hud.py picks it from the data */
        set_bkg_attribute_xy_nes16x16(c, 1u, HUD_SKY_PAL);
    set_sprite_tile(OAM_HUD, HUD_SPR_T0);                /* markers: Kop white, thief red, car yellow (colours chosen by gen_hud.py) */
    set_sprite_prop(OAM_HUD, HUD_SPR_PROP0);
    set_sprite_tile(OAM_HUD + 1u, HUD_SPR_T0 + 1u);
    set_sprite_prop(OAM_HUD + 1u, HUD_SPR_PROP1);
    set_sprite_tile(OAM_HUD + 2u, HUD_SPR_T0 + 2u);
    set_sprite_prop(OAM_HUD + 2u, HUD_SPR_PROP2);
    if (band_mode) {
        SWITCH_ROM(HUD_BANK);
        put_text(title_msg ? 11u : 8u, BAND_ROW, title_msg ? "GAME OVER" : "KEYSTONE KAPERS", HT_FONT_L, hud_bmap);
        put_text(9u, BAND_ROW + 1u, "SELECT LEVEL", HT_FONT_L, hud_bmap);
        put_text(10u, BAND_ROW + 2u, "PRESS START", HT_FONT_L, hud_bmap);
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
    set_bkg_palette(0u, 4u, bg_pal);                     /* bg_pal is shared; screen 4 redefines one slot (dyn) */
    set_bkg_data(0u, bg_ntiles[s], bg_chr[s]);
    dyn_load_chr(s);                                     /* escalator / elevator tiles after the bg tiles */
    fill_bkg_rect(0u, 0u, 32u, 2u, HT_BLACK);            /* top margin ... */
    fill_bkg_rect(0u, 26u, 32u, 4u, HT_BLACK);           /* ... and the band below the playfield */
    for (y = 0u; y < 15u; y++)
        if (y >= 13u || y == 0u)                         /* attr rows of the margins (1..12 = playfield) */
            for (x = 0u; x < 16u; x++)
                set_bkg_attribute_xy_nes16x16(x, y, HUD_MARGIN_PAL);
    set_bkg_tiles(0u, 2u, BG_W, BG_H, bg_map[s]);
    for (y = 0u; y < BG_H / 2u; y++)
        for (x = 0u; x < BG_W / 2u; x++)
            set_bkg_attribute_xy_nes16x16(x, 1u + y, bg_attr[s][y * (BG_W / 2u) + x]);
    dyn_screen(s);                                       /* animated scenery: current phase / door state */
    hud_static();
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
    uint8_t n = spr_frame_ntiles[frame];     /* two 8 px columns per tile row at 13 px wide */
    if (x < OBJ_MIN_X || x >= OBJ_MAX_X || (uint8_t)(r_o + n) > OAM_LIMIT)
        return;                              /* off the playfield, or OAM full: skip the whole actor */
    r_o += move_metasprite_ex(spr_frame[frame][flip ? 1u : 0u], SPR_TILE_BASE, 0u, r_o,
                              (int16_t)PF_X[x - OBJ_X_OFS], SPR_Y(pf_y));
}

static void render(void)
{
    uint8_t f, fr;
    if (kop_screen != shown_screen)
        show_screen(kop_screen & 7u);
    dyn_update();
    SWITCH_ROM(SPR_BANK);                    /* widened frame tables (bank 3) are read from here on */
    r_o = OAM_KOP;
    /* Kop: feet = floor line - $1C (bits 5-7 = floor marker, 0-4 = height); hidden in the closed car */
    if (!dyn_kop_hidden())
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

/* ---------------------------------------------------------------- HUD */

#ifndef DEBUG_TRACE
/* score (leading zeros blank) | lives as hats | time | level; title: the selected level too */
static void hud(uint8_t lvl)
{
    uint8_t i, z;
    if (hud_last[0] == score_hi && hud_last[1] == score_lo && hud_last[2] == game_time
            && hud_last[3] == lives && hud_last[4] == lvl)
        return;
    hud_last[0] = score_hi;
    hud_last[1] = score_lo;
    hud_last[2] = game_time;
    hud_last[3] = lives;
    hud_last[4] = lvl;
    hud_buf[0] = score_hi >> 4;
    hud_buf[1] = score_hi & 0x0Fu;
    hud_buf[2] = score_lo >> 4;
    hud_buf[3] = score_lo & 0x0Fu;
    hud_buf[4] = 0u;
    z = 1u;
    for (i = 0u; i < 5u; i++) {
        if (z && hud_buf[i] == 0u)
            hud_buf[i] = SKY_SPACE;
        else {
            z = 0u;
            hud_buf[i] += HT_FONT_S;
        }
    }
    hud_buf[5] = HT_FONT_S;                              /* the score ends in "00" */
    set_bkg_tiles(8u, 2u, 6u, 1u, hud_buf);
    for (i = 0u; i < 3u; i++)
        hud_buf[i] = (i < lives) ? HT_HAT : SKY_SPACE;
    set_bkg_tiles(2u, 3u, 3u, 1u, hud_buf);
    put_bcd(21u, 2u, game_time, HT_FONT_S, 0);
    if (lvl >= 10u)
        lvl = (uint8_t)(0x10u | (uint8_t)(lvl - 10u));
    put_bcd(28u, 2u, lvl, HT_FONT_S, 0);
    if (band_mode) {
        SWITCH_ROM(HUD_BANK);
        put_bcd(22u, BAND_ROW + 1u, lvl, HT_FONT_L, hud_bmap);
    }
}

/* minimap marker (2x2 px sprite on the baked box): 16 px per screen, 16 world px per map px */
static void mark(uint8_t slot, uint8_t scr, uint8_t fl, uint8_t x)
{
    uint8_t v = (x > 0x2Cu) ? (uint8_t)((((uint16_t)(x - 0x2Cu) * 8u) / 5u) >> 4) : 0u;
    if (v > 13u)
        v = 13u;
    move_sprite((uint8_t)(OAM_HUD + slot), (uint8_t)(MAP_X0 + MAP_CELL_W * (7u - scr) + v),
                (uint8_t)(MAP_Y_TOP + 4u * (3u - fl) + DEVICE_SPRITE_PX_OFFSET_Y));
}

static void markers(void)
{
    mark(0u, kop_screen, KOP_FLOOR(), KOP_X());
    if (thief_escaped)
        hide_sprite(OAM_HUD + 1u);
    else
        mark(1u, thief_screen(), THIEF_FLOOR(), thief_x);
    mark(2u, 4u, car_floor(), 0x78u);                    /* elevator shaft on screen 4 */
}
#endif
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
    /* Static tiles/palettes: identical for every screen, so uploading them once here keeps them out
     * of the per-screen black flip (about 1.7 KB, ~4-5 frames; docs/NES_FULL_WIDTH_PLAN.md). */
#ifdef NINTENDO_NES
    PPUCTRL = shadow_PPUCTRL & (uint8_t)~(PPUCTRL_NMI | PPUCTRL_INC32);
#endif
    SWITCH_ROM(HUD_BANK);
    set_bkg_data(HUD_T0, HUD_NTILES, hud_tiles);
    set_sprite_data(HUD_SPR_T0, HUD_NSPR, hud_spr);
    SWITCH_ROM(SPR_BANK);                    /* spr_palettes and spr_chr live in the sprite bank */
    set_sprite_palette(0u, 4u, spr_palettes);
    set_sprite_data(SPR_TILE_BASE, SPR_NTILES, spr_chr);
#ifdef NINTENDO_NES
    PPUCTRL = shadow_PPUCTRL;
#endif
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
    band_mode = 1u;
    for (;;) {
        pad_old = pad;
        pad = joypad();
        if (gs == GS_TITLE) {
            rng_s += 0x3Du;                  /* the moment START is pressed seeds the RNG */
            eng_events = 0u;                 /* before game_new(): keeps EV_MUSIC_ON (C5) */
            if (lock)
                lock--;
            else if ((pad & J_SELECT) && !(pad_old & J_SELECT))
                start_sel = (start_sel >= 16u) ? 1u : (uint8_t)(start_sel + 1u);
            else if ((pad & J_START) && !(pad_old & J_START)) {
                game_new(start_sel);
                gs = GS_PLAY;
                band_mode = 0u;
                shown_screen = 0xFFu;        /* redraw: minimap instead of the title text */
            }
        } else {
            engine_frame(read_input(pad));
            if (game_over) {
                gs = GS_TITLE;
                lock = 120u;                 /* keep the final score on screen a moment */
                band_mode = 1u;
                title_msg = 1u;
                shown_screen = 0xFFu;
            }
        }
        sound_events();
        render();
        hud(gs == GS_TITLE ? start_sel : (uint8_t)(level + 1u));
        markers();
        vsync();
        snd_tick();
    }
#endif
}
