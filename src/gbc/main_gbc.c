/*
 * main_gbc.c - Keystone Kapers on the Game Boy (one ROM, header $80: CGB colour path on a Game Boy Color,
 * DMG 4-shade path on a Game Boy; gb_color = (_cpu == CGB_TYPE) picks it at boot): game loop, state machine
 * and renderer.  The game logic is the shared engine (src/engine.c, src/obstacle.c: world coordinates);
 * this file is the GB camera and display, the counterpart of src/main.c (NES).  The title / play /
 * game-over flow is a copy of src/main.c main() (keep the two in step; DECISIONS_PENDING C-log).
 * Data: CGB = src/gbc/gbc_data.h (tiles in VRAM bank 1 + attributes + palettes), DMG = src/dmg/dmg_data.h
 * (tiles after the HUD ids, BGP/OBP0/OBP1, sprite shades baked in dmg_spr_chr).  Every VBK / attribute /
 * palette write is CGB-only: on a DMG a missed VBK switch would write attributes into the tile map.
 *
 * Screen (160x144, 1:1 with the Atari's 160 colour clocks, no pillarbox):
 *   lines 0..VIEW_H-1  BG = the 160x181 playfield (src/gbc/gbc_bank*.c, one screen at a time), scrolled
 *                      vertically by cam_y (playfield line at the top of the screen): it follows Kop's
 *                      floor between CAM_F3 (floor 3) and CAM_F0 (floor 0) - all four floors stay visible.
 *   window             HUD: minimap (left 80 px, Kop / thief / car markers as sprites), score + time,
 *                      level + hats (right 80 px); on the title 3 more text rows above it (KEYSTONE KAPERS /
 *                      SELECT LEVEL nn / PRESS START), with the camera lowered so floors 0-2 stay visible.
 * VRAM: screen tiles in bank 1 (attr bit 3), HUD tiles bank 0 BG ids 0.., sprite tiles bank 0 OBJ ids 0..
 * Palettes: BG 0-5 per screen, 6 minimap, 7 HUD text; OBJ 0-3 sprites, 4-6 minimap markers.
 * Screen flip: BG palettes black, tiles/map/attributes rewritten with the display on (library calls wait
 * for VRAM access), palettes back (a few black frames, like the NES flip E5).
 */
#include "platform.h"
#include <stdint.h>

#include "engine.h"
#include "sound.h"
#include "spr_data.h"
#include "gbc_data.h"
#include "dmg_data.h"
#include "dyn_gbc.h"

/* ---- camera */
#define VIEW_PLAY    128u   /* BG lines above the HUD window while playing (2 window rows) */
#define VIEW_TITLE   104u   /* title: 5 window rows */
#define CAM_F0       31u    /* cam_y with Kop on floor 0 (shows lines 31..158: street top) */
#define CAM_F3       23u    /* floor 3 (lines 23..150: Kop's jump top on the roof .. floor-0 feet) */
#define CAM_TITLE    48u    /* title: floors 0-2 above the taller window */
#define OBJ_X_OFS    0x30u  /* Atari HPOS of playfield px 0 (G1) = GBC screen x 0 */
#define FEET_Y0      147u   /* playfield line of the feet on floor 0 at height 0 */
#define FLOOR_DY     32u

/* ---- OAM (40 slots) */
#define OAM_GAME     37u    /* Kop 3 + thief 3 + objects <= 24 */
#define OAM_MARK     37u    /* 3 minimap markers */
#define MARK_TILE    0x7Fu  /* CGB: OBJ tile id of the marker (sprite tiles 0..SPR_NTILES-1) */
#define MARK_PAL     4u

/* ---- window HUD */
#define HUD_COL      10u    /* text block columns 10..19 (minimap 0..9) */
#define TXT_ATTR     (GBC_PAL_TXT | 0x80u)   /* CGB: BG-over-OBJ priority, text hides sprites */
#define MAP_ATTR     GBC_PAL_MAP

uint8_t gb_color;                     /* 1 = Game Boy Color hardware (colour path), 0 = DMG shades */
static uint8_t pal_mask;            /* OBJ prop palette bits kept: 3 on CGB, 0 on DMG (OBP0) */
static uint8_t shown_screen = 0xFFu;
static uint8_t oam_n, oam_used = OAM_GAME;
static uint8_t cam_y, cam_t, cam_tick, cam_snap = 1u;
static uint8_t view_h = VIEW_PLAY, win_y = VIEW_PLAY, hud_row;
static uint8_t hud_buf[20];
static uint8_t hud_last[5];
static uint8_t band_mode;           /* 0 play HUD, 1 title text */
static uint8_t hud_band = 0xFFu;    /* band the window shows */
static uint8_t title_msg;           /* 0 power-on, 1 game over */
static uint8_t r_i, r_n, r_f;
static int16_t d_x, d_y;
static const metasprite_t *d_m;
static const uint16_t black_pal[GBC_NPAL * 4u] = { 0 };

#if DMG_TILE_BASE != GBC_HUD_NTILES
#error "DMG screen tiles must start right after the HUD tiles (gen_dmg_assets.py)"
#endif

/* ---------------------------------------------------------------- HUD (window) */

static uint8_t ch_tile(char c)
{
    if (c >= '0' && c <= '9')
        return (uint8_t)(GBC_HT_FONT + (uint8_t)(c - '0'));
    if (c >= 'A' && c <= 'Z')
        return (uint8_t)(GBC_HT_FONT + 10u + (uint8_t)(c - 'A'));
    if (c == ':')
        return GBC_HT_FONT + 37u;
    if (c == '-')
        return GBC_HT_FONT + 38u;
    if (c == '!')
        return GBC_HT_FONT + 39u;
    return GBC_HT_SPACE;
}

static void win_row(uint8_t x, uint8_t y, uint8_t n, uint8_t attr)
{
    set_win_tiles(x, y, n, 1u, hud_buf);
    if (gb_color) {
        for (r_i = 0u; r_i < n; r_i++)
            hud_buf[r_i] = attr;
        VBK_REG = VBK_ATTRIBUTES;
        set_win_tiles(x, y, n, 1u, hud_buf);
        VBK_REG = VBK_TILES;
    }
}

static void put_text(uint8_t x, uint8_t y, const char *s)
{
    for (r_n = 0u; s[r_n]; r_n++)
        hud_buf[r_n] = ch_tile(s[r_n]);
    win_row(x, y, r_n, TXT_ATTR);
}

static void put_bcd(uint8_t x, uint8_t y, uint8_t v)
{
    hud_buf[0] = (uint8_t)(GBC_HT_FONT + (v >> 4));
    hud_buf[1] = (uint8_t)(GBC_HT_FONT + (v & 0x0Fu));
    win_row(x, y, 2u, TXT_ATTR);
}

/* whole window: title rows (band_mode), minimap, labels */
static void hud_static(void)
{
    uint8_t y;
    hud_row = band_mode ? 3u : 0u;
    win_y = band_mode ? VIEW_TITLE : VIEW_PLAY;
    view_h = win_y;
    for (y = 0u; y < 5u; y++)
        put_text(0u, y, "                    ");
    for (y = 0u; y < 2u; y++) {
        for (r_n = 0u; r_n < 10u; r_n++)
            hud_buf[r_n] = (uint8_t)(GBC_HT_MAP + y * 10u + r_n);
        win_row(0u, (uint8_t)(hud_row + y), 10u, MAP_ATTR);
    }
    put_text(HUD_COL + 7u, hud_row, "T");
    put_text(HUD_COL, (uint8_t)(hud_row + 1u), "LV");
    if (band_mode) {
        put_text(title_msg ? 5u : 2u, 0u, title_msg ? "GAME OVER" : "KEYSTONE KAPERS");
        put_text(2u, 1u, "SELECT LEVEL");
        put_text(4u, 2u, "PRESS START");
    }
    hud_last[0] = 0xFFu;
}

/* score (leading zeros blank) T time | LV level, hats; title: the selected level too */
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
            hud_buf[i] = GBC_HT_SPACE;
        else {
            z = 0u;
            hud_buf[i] += GBC_HT_FONT;
        }
    }
    hud_buf[5] = GBC_HT_FONT;                            /* the score ends in "00" */
    win_row(HUD_COL, hud_row, 6u, TXT_ATTR);
    put_bcd(HUD_COL + 8u, hud_row, game_time);
    if (lvl >= 10u)
        lvl = (uint8_t)(0x10u | (uint8_t)(lvl - 10u));
    put_bcd(HUD_COL + 2u, (uint8_t)(hud_row + 1u), lvl);
    for (i = 0u; i < 3u; i++)
        hud_buf[i] = (i < lives) ? GBC_HT_HAT : GBC_HT_SPACE;
    win_row(HUD_COL + 5u, (uint8_t)(hud_row + 1u), 3u, TXT_ATTR);
    if (band_mode)
        put_bcd(15u, 1u, lvl);
}

/* minimap marker: 10 px per screen (screen 0 at the right end), 16 world px per map px, 4 lines per floor */
static void mark(uint8_t slot, uint8_t scr, uint8_t fl, uint8_t x)
{
    uint8_t v = (x > 0x2Cu) ? (uint8_t)((x - 0x2Cu) >> 4) : 0u;
    if (v > 9u)
        v = 9u;
    move_sprite((uint8_t)(OAM_MARK + slot), (uint8_t)(DEVICE_SPRITE_PX_OFFSET_X + 10u * (7u - scr) + v),
                (uint8_t)(DEVICE_SPRITE_PX_OFFSET_Y + win_y + hud_row * 8u + 1u + 4u * (3u - fl)));
}

static void markers(void)
{
    mark(0u, kop_screen, KOP_FLOOR(), KOP_X());
    if (thief_escaped)
        hide_sprite(OAM_MARK + 1u);
    else
        mark(1u, thief_screen(), THIEF_FLOOR(), thief_x);
    mark(2u, 4u, car_floor(), 0x78u);                    /* elevator shaft on screen 4 */
}

/* ---------------------------------------------------------------- background */

static void camera(void);

static void show_screen(uint8_t s)
{
    for (r_i = 0u; r_i < OAM_GAME; r_i++)    /* hidden by the OAM DMA of the same VBlank as the black palettes */
        shadow_OAM[r_i].y = 0u;
    oam_used = 0u;
    vsync();
    if (gb_color) {
        set_bkg_palette(0u, GBC_NPAL, black_pal);
        SWITCH_ROM(gbc_bank[s]);
        VBK_REG = VBK_BANK_1;
        set_bkg_data(0u, gbc_ntiles[s], gbc_chr[s]);
        VBK_REG = VBK_BANK_0;
        set_bkg_tiles(0u, 0u, GBC_BG_W, GBC_BG_H, gbc_map[s]);
        set_bkg_attributes(0u, 0u, GBC_BG_W, GBC_BG_H, gbc_attr[s]);
    } else {
        BGP_REG = 0xFFu;                     /* all black while the tiles are rewritten (HUD too, D4) */
        SWITCH_ROM(dmg_bank[s]);
        /* screen tiles = BG ids DMG_TILE_BASE..; ids >= 128 live at $8800: a second call */
        r_n = dmg_ntiles[s];
        r_f = (uint8_t)(128u - DMG_TILE_BASE);
        if (r_n <= r_f)
            set_bkg_data(DMG_TILE_BASE, r_n, dmg_chr[s]);
        else {
            set_bkg_data(DMG_TILE_BASE, r_f, dmg_chr[s]);
            set_bkg_data(128u, (uint8_t)(r_n - r_f), dmg_chr[s] + ((uint16_t)r_f << 4));
        }
        set_bkg_tiles(0u, 0u, GBC_BG_W, GBC_BG_H, dmg_map[s]);
    }
    gdyn_screen(s);
    if (band_mode != hud_band) {             /* the window only changes with the title/play band */
        hud_band = band_mode;
        hud_static();
    }
    shown_screen = s;
    camera();                                /* band_mode may have changed: the new screen shows at its scroll */
    if (gb_color)
        SWITCH_ROM(gbc_bank[s]);             /* gbc_pal[s] is banked */
    vsync();
    SCY_REG = cam_y;
    WY_REG = win_y;
    if (gb_color)
        set_bkg_palette(0u, GBC_NPAL, gbc_pal[s]);
    else
        BGP_REG = DMG_BGP;
}

/* cam_y follows Kop's floor (1 line every 2 frames); title: fixed */
static void camera(void)
{
    cam_t = band_mode ? CAM_TITLE : (uint8_t)(CAM_F0 - (uint8_t)((uint8_t)(KOP_FLOOR() * (CAM_F0 - CAM_F3)) / 3u));
    if (cam_snap) {
        cam_y = cam_t;
        cam_snap = 0u;
    } else if (cam_y != cam_t && (++cam_tick & 1u)) {
        cam_y = (cam_y < cam_t) ? (uint8_t)(cam_y + 1u) : (uint8_t)(cam_y - 1u);
    }
}

/* ---------------------------------------------------------------- sprites */

/* spr_data metasprites carry NES props (bits 0-1 palette, 0x40 mirror): remapped to CGB (S_FLIPX);
 * DMG: palette bits dropped (pal_mask 0 = OBP0, the shades are baked in dmg_spr_chr).
 * Each 8x8 tile is placed on its own: tiles outside the playfield view are dropped. */
static void draw(uint8_t frame, uint8_t flip, uint8_t x, uint8_t pf_y)
{
    d_m = spr_frame[frame][flip ? 1u : 0u];
    d_x = (int16_t)x - (int16_t)OBJ_X_OFS;
    d_y = (int16_t)pf_y - (int16_t)cam_y;
    while (d_m->dy != (int8_t)metasprite_end) {
        d_y += d_m->dy;
        d_x += d_m->dx;
        if (oam_n < OAM_GAME && d_y > -8 && d_y < (int16_t)view_h && d_x > -8 && d_x < 160) {
            shadow_OAM[oam_n].y = (uint8_t)(d_y + DEVICE_SPRITE_PX_OFFSET_Y);
            shadow_OAM[oam_n].x = (uint8_t)(d_x + DEVICE_SPRITE_PX_OFFSET_X);
            shadow_OAM[oam_n].tile = (uint8_t)(SPR_TILE_BASE + d_m->dtile);
            shadow_OAM[oam_n].prop = (uint8_t)((d_m->props & pal_mask) | ((d_m->props & 0x40u) ? S_FLIPX : 0u));
            oam_n++;
        }
        d_m++;
    }
}

static void render(void)
{
    uint8_t f, fr;
    if (kop_screen != shown_screen)
        show_screen(kop_screen & 7u);
    gdyn_update();
    camera();
    oam_n = 0u;
    if (!gdyn_kop_hidden())
        draw(spr_kop_pose[kop_pose & 7u], kop_face & 8u, KOP_X(), (uint8_t)(FEET_Y0 - kop_c1c));
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
        for (r_f = 0u; r_f < r_n; r_f++)
            draw(fr, obj_fl[f] & 8u, obj_cx[r_f],
                 (uint8_t)(FEET_Y0 - FLOOR_DY * f + obj_h[f] - 0x1Au));
    }
    for (r_i = oam_n; r_i < oam_used; r_i++)
        shadow_OAM[r_i].y = 0u;
    oam_used = oam_n;
}

/* ---------------------------------------------------------------- sound (= src/main.c) */

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

/* ---------------------------------------------------------------- init */

static void gfx_init(void)
{
    gb_color = (_cpu == CGB_TYPE) ? 1u : 0u;   /* CGB-compatible header ($80): GBDK keeps the boot A register */
    pal_mask = gb_color ? 3u : 0u;
    if (gb_color)
        cpu_fast();
    DISPLAY_OFF;
    LCDC_REG = LCDCF_OFF | LCDCF_WIN9C00 | LCDCF_BG8800 | LCDCF_BG9800 | LCDCF_OBJ8 | LCDCF_BGON;
    if (gb_color) {
        VBK_REG = VBK_BANK_0;
        SWITCH_ROM(GBC_HUD_BANK);
        set_bkg_data(0u, GBC_HUD_NTILES, gbc_hud_chr);   /* window tiles: bank 0, $9000.. */
        set_sprite_data(SPR_TILE_BASE, SPR_NTILES, spr_chr);
        set_sprite_data(MARK_TILE, 1u, gbc_marker_chr);
        set_bkg_palette(GBC_PAL_MAP, 2u, gbc_hud_pal);
        set_bkg_palette(0u, GBC_NPAL, black_pal);
        set_sprite_palette(0u, 7u, gbc_obj_pal);
    } else {
        SWITCH_ROM(DMG_HUD_BANK);
        set_bkg_data(0u, GBC_HUD_NTILES, dmg_hud_chr);   /* same HUD ids, shades instead of palettes */
        set_sprite_data(SPR_TILE_BASE, SPR_NTILES, dmg_spr_chr);
        set_sprite_data(DMG_MARK_TILE_A, 2u, dmg_marker_chr);
        BGP_REG = 0xFFu;                                 /* black until the first screen is shown */
        OBP0_REG = DMG_OBP0;
        OBP1_REG = DMG_OBP1;
    }
    for (r_i = 0u; r_i < 40u; r_i++)
        shadow_OAM[r_i].y = 0u;
    for (r_i = 0u; r_i < 3u; r_i++) {
        if (gb_color) {
            set_sprite_tile((uint8_t)(OAM_MARK + r_i), MARK_TILE);
            set_sprite_prop((uint8_t)(OAM_MARK + r_i), (uint8_t)(MARK_PAL + r_i));
        } else {    /* Kop: tile A OBP0 white, thief: tile B black, car: tile A OBP1 light grey */
            set_sprite_tile((uint8_t)(OAM_MARK + r_i), (r_i == 1u) ? DMG_MARK_TILE_B : DMG_MARK_TILE_A);
            set_sprite_prop((uint8_t)(OAM_MARK + r_i), (r_i == 2u) ? S_PALETTE : 0u);
        }
    }
    SCX_REG = 0u;
    SCY_REG = 0u;
    WX_REG = 7u;
    WY_REG = VIEW_PLAY;
    SHOW_BKG;
    SHOW_WIN;
    SHOW_SPRITES;
    DISPLAY_ON;
}

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

/* states: title (power-on / after a game over; attract demo not ported, G5) and play */
#define GS_TITLE 0u
#define GS_PLAY  1u
static uint8_t gs, start_sel = 1u, pad, pad_old, lock;

void main(void)
{
    gfx_init();
    snd_init();
    engine_init();
    play_on = 0u;                            /* title: frozen level-start scene */
    gs = GS_TITLE;
    band_mode = 1u;
    for (;;) {
        pad_old = pad;
        pad = joypad();
        if (gs == GS_TITLE) {
            rng_s += 0x3Du;                  /* the moment START is pressed seeds the RNG */
            eng_events = 0u;                 /* before game_new(): its EV_MUSIC_ON must reach sound_events()
                                              * (src/main.c clears it after, so the NES tune does not start, C5) */
            if (lock)
                lock--;
            else if ((pad & J_SELECT) && !(pad_old & J_SELECT))
                start_sel = (start_sel >= 16u) ? 1u : (uint8_t)(start_sel + 1u);
            else if ((pad & J_START) && !(pad_old & J_START)) {
                game_new(start_sel);
                gs = GS_PLAY;
                band_mode = 0u;
                cam_snap = 1u;
                shown_screen = 0xFFu;        /* redraw: play HUD instead of the title text */
            }
        } else {
            engine_frame(read_input(pad));
            if (game_over) {
                gs = GS_TITLE;
                lock = 120u;                 /* keep the final score on screen a moment */
                band_mode = 1u;
                title_msg = 1u;
                cam_snap = 1u;
                shown_screen = 0xFFu;
            }
        }
        sound_events();
        render();
        hud(gs == GS_TITLE ? start_sel : (uint8_t)(level + 1u));
        markers();
        vsync();
        SCY_REG = cam_y;
        WY_REG = win_y;
        snd_tick();
    }
}
