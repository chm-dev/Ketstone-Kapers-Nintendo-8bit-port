/*
 * engine.c - Keystone Kapers game logic (shared C, no platform calls).
 * Line-by-line port of tools/kk_model.py (Kop, thief, timer) and tools/kk_game_model.py (main-loop
 * flow A436..A974: bonus, hit/death gating, collisions, effect countdown, restart); Atari addresses
 * in comments.  Keep it literal: the golden traces (tests/golden) are matched frame-exactly by
 * tests/run_c_trace.ps1.
 */
#include "engine.h"

/* ROM tables (docs/ATARI_RE_SPEC.md 6b, 7) */
static const uint8_t B8D4[4] = { 0x90u, 0x65u, 0x90u, 0xA8u }; /* escalator base X per floor */
static const uint8_t B8D7[4] = { 0xA8u, 0x80u, 0xA8u, 0x6Eu }; /* $0C while riding (A8 left, 80 right) */
static const uint8_t B9E3[4] = { 0x07u, 0x00u, 0x07u, 0xE0u }; /* screen holding floor f's escalator */
static const uint8_t BBA1[4] = { 0x04u, 0x0Bu, 0x14u, 0x0Bu }; /* $1D per elevator car floor */
static const uint8_t BBA2[4] = { 0x0Bu, 0x14u, 0x0Bu, 0x04u }; /* thief $1F that holds the car */
static const uint8_t B5F7[4] = { 0x02u, 0x05u, 0x04u, 0x10u }; /* pickup score per floor (BCD hundreds) */
static const uint8_t BEF2[3] = { 0xA0u, 0x80u, 0x60u };        /* radio copy test X */
static const uint8_t BEF8[3] = { 0x06u, 0x05u, 0x03u };        /* radio alive mask kept */
static const uint8_t BEE1[8] = { 0x00u, 0x00u, 0x00u, 0x07u, 0x00u, 0x04u, 0x07u, 0x06u };
static const uint8_t BEE9[8] = { 0x00u, 0x98u, 0x78u, 0x78u, 0x58u, 0x58u, 0x58u, 0x58u };

uint8_t kop_xs[4];
uint8_t kop_path, kop_screen, kop_face, kop_pose, kop_jump, kop_c1c, kop_latch, kop_stick;
uint8_t elev_8e, elev_6b, kop_ad_pending;
uint8_t thief_x, thief_path, thief_anim, thief_escaped, game_time;
uint8_t frame_90, frame_8f;
uint8_t play_on, bonus_on, snd_id, snd_cnt, e_6c, lives, level, level_start, score_hi, score_lo;
uint8_t game_over, kop_col, kop_col_next;
uint16_t intro_cnt;
uint8_t eng_events, eng_sfx;
uint16_t rng_s = 0xACE1u;

/* scratch shared by the step functions (SDCC: flat statics, no deep stack use) */
static uint8_t e_f, e_x, e_t, bcd_c;

uint8_t car_floor(void)
{
    e_t = elev_6b & 3u;
    return (e_t == 3u) ? 1u : e_t;
}

uint8_t thief_screen(void)                 /* $11 */
{
    e_t = thief_path & 0x0Fu;
    return (e_t >= 8u) ? (uint8_t)(e_t ^ 0x0Fu) : e_t;
}

uint8_t eng_rand(void)                     /* 16-bit Galois LFSR, 8 steps */
{
    uint8_t i;
    for (i = 0u; i < 8u; i++)
        rng_s = (rng_s & 1u) ? (uint16_t)((rng_s >> 1) ^ 0xB400u) : (uint16_t)(rng_s >> 1);
    return (uint8_t)rng_s;
}

/* ---------------------------------------------------------------- score, effects */

static uint8_t bcd_add(uint8_t x, uint8_t y)
{
    uint8_t lo = (uint8_t)((x & 0x0Fu) + (y & 0x0Fu) + bcd_c), hi = (uint8_t)((x >> 4) + (y >> 4));
    if (lo > 9u) {
        lo -= 10u;
        hi++;
    }
    bcd_c = 0u;
    if (hi > 9u) {
        hi -= 10u;
        bcd_c = 1u;
    }
    return (uint8_t)((hi << 4) | lo);
}

static void time_dec(void)                 /* S_AED2 (only when > 0) */
{
    if (game_time & 0x0Fu)
        game_time--;
    else
        game_time = (uint8_t)(((game_time - 0x10u) & 0xF0u) | 9u);
}

/* S_AF10: score += a (BCD hundreds); extra life when the ten-thousands pair changes (max 3) */
static void score_add(uint8_t a)
{
    uint8_t old = score_hi;
    bcd_c = 0u;
    score_lo = bcd_add(score_lo, a);
    score_hi = bcd_add(score_hi, 0u);
    if (bcd_c) {                               /* overflow: $25..$27 = $AA, game ends */
        score_hi = 0xAAu;
        score_lo = 0xAAu;
        play_on = 0u;
        bonus_on = 0u;
        game_over = 1u;
        eng_events |= EV_MUSIC_OFF;
    }
    if (old != score_hi && lives < 3u)
        lives++;
}

static void sfx_start(uint8_t id, uint8_t cnt)
{
    snd_id = id;
    snd_cnt = cnt;
    eng_sfx = id;
    eng_events |= EV_SFX;
}

/* A825: death (time out, plane, thief escaped) */
static void death_start(void)
{
    sfx_start(6u, 8u);
}

/* A49A + S_AF8F: restart the level (after a death with lives left, or the next level) */
static void level_restart(void)
{
    kop_face = 0u;                             /* $0C..$1A = 0 */
    kop_col = 0u;
    kop_col_next = 0u;
    snd_cnt = 0u;
    bonus_on = 0u;
    play_on = 0u;
    snd_id = 0u;
    kop_latch = 0u;
    kop_jump = 0u;
    thief_escaped = 0u;
    obj_6e = 0u;
    /* S_AF98 Y=5: $1B..$20 from $B9BB, $2C = $7A, $28 = $50 */
    thief_x = 0x7Au;
    kop_c1c = 0u;
    kop_path = 0u;
    kop_screen = 0u;
    thief_path = 0x0Bu;
    kop_pose = 6u;
    kop_xs[0] = 0x7Au;
    game_time = 0x50u;
    obj_pickups();
    obj_spawn();
    level = level_start;
    intro_cnt = RESTART_WAIT;
    eng_events |= EV_MUSIC_ON | EV_SCREEN;
}

/* A877..A8E9: effect countdown and its end actions */
static void sfx_tick(void)
{
    uint8_t id = snd_id;
    if (!id)
        return;
    if (id >= 4u && (frame_90 & 3u))
        return;
    snd_cnt--;
    if (!(snd_cnt & 0x80u))
        return;
    if (id == 6u) {
        if (!lives) {                          /* A8AC: game over */
            play_on = 0u;
            game_over = 1u;
            eng_events |= EV_MUSIC_OFF;
        } else {
            lives--;
            level_start = level;
            level_restart();                   /* JMP A49A ($17 = 0) */
        }
    } else if (id >= 4u) {                     /* A8C1: hit / pickup over, slot restored */
        e_f = KOP_FLOOR();
        obj_t[e_f] = obj_6e;
        obj_x[e_f] = obj_rx;
        obj_fl[e_f] = obj_rfl;
        obj_6e = 0u;
    }
    snd_id = 0u;                               /* A8E2 */
    eng_events |= EV_SFX_END;
}

/* A776..A82D: Kop touched the object of his floor ($0D+f latched) */
static void collide(void)
{
    uint8_t t, i;
    e_f = KOP_FLOOR();
    t = obj_t[e_f];
    if (!t)
        return;
    if (t < 6u) {                              /* A7FF: the thief is caught */
        if (kop_screen == 7u && kop_c1c >= 0x60u && kop_xs[e_f] >= 0x6Cu && kop_xs[e_f] < 0x88u)
            return;                            /* roof exception */
        eng_events |= EV_MUSIC_OFF;            /* S_AF76 */
        score_add(0x10u);
        bonus_on = 0xFFu;
        play_on = 0u;
        return;
    }
    if (t < 8u) {                              /* A791: radio, only below jump height 6 */
        if ((kop_c1c & 0x1Fu) >= 6u)
            return;
        obj_6e = t;
        e_6c = kop_xs[e_f];
        i = 3u;
        do {
            i--;
            if ((uint8_t)(BEF2[i] - e_6c) < 0x11u)
                break;
        } while (i);
        e_x = ((uint8_t)(BEF2[i] - e_6c) < 0x11u) ? BEF8[i] : 0x61u;   /* not found: $BEF8-1 = $61 */
        obj_6f &= e_x;
        obj_rfl = BEE1[obj_6f & 7u];
        obj_rx = BEE9[obj_6f & 7u];
    }
    if (t < 10u) {                             /* A7F4: hit, 9 x 4 frames frozen */
        sfx_start(5u, 8u);
        return;
    }
    if (t < 12u) {                             /* plane: death */
        death_start();
        return;
    }
    if (t < 0x0Fu)
        return;
    pickup_scr[e_f] = t;                       /* A7D4: collected */
    obj_t[e_f] = 2u;
    score_add(B5F7[e_f]);
    sfx_start(4u, 8u);
}

/* ---------------------------------------------------------------- init */

void engine_init(void)
{
    /* level init A27A / AF98: $B9BB table -> $1B=$7A $1C=0 $1D=0 $1E=0 $1F=$0B $20=6, $2C=$7A, $28=$50 */
    kop_xs[0] = 0x7Au; kop_xs[1] = 0u; kop_xs[2] = 0u; kop_xs[3] = 0u;
    kop_path = 0u; kop_screen = 0u; kop_face = 0u; kop_pose = 6u;
    kop_jump = 0u; kop_c1c = 0u; kop_latch = 0u; kop_stick = 0u;
    elev_8e = 0u; elev_6b = 0u; kop_ad_pending = 0u;      /* DECISIONS_PENDING E2 */
    thief_x = 0x7Au; thief_path = 0x0Bu; thief_anim = 3u; thief_escaped = 0u;
    game_time = 0x50u;
    frame_90 = 0u; frame_8f = 0u;
    eng_events = 0u; eng_sfx = 0u;
    play_on = 0xFFu; bonus_on = 0u; snd_id = 0u; snd_cnt = 0u; e_6c = 0u;
    lives = 3u; level = 0u; level_start = 0u; score_hi = 0u; score_lo = 0u;
    game_over = 0u; intro_cnt = 0u; kop_col = 0u; kop_col_next = 0u;
    obj_reset();
    pickup_scr[0] = 2u; pickup_scr[1] = 2u; pickup_scr[2] = 2u; pickup_scr[3] = 1u;  /* level-1 layout seen */
    obj_spawn();
}

void game_new(uint8_t start)
{
    /* A371/A27A/A292: start level $03 (1..16) -> $93 = $22 = start-1; $21=3, score 0 */
    level_start = (uint8_t)(start - 1u);
    lives = 3u;
    score_hi = 0u;
    score_lo = 0u;
    game_over = 0u;
    level_restart();
    intro_cnt = INTRO_WAIT;
}

/* ---------------------------------------------------------------- Kop */

static uint8_t riding(void)
{
    return (kop_face & 0x80u) && !(kop_face & 0x40u);
}

/* AD0F..AD62 (only while Kop is on screen 4): door window / departure / thief interlock */
static void elevator_logic(void)
{
    e_t = elev_8e & 0x7Fu;
    if (e_t < 0x70u || ((e_t >> 2) & 3u) != 1u)
        return;
    if (!(elev_8e & 0x80u)) {
        elev_8e = 0x80u;                       /* $74-$77: open the doors */
        return;
    }
    if (thief_path == BBA2[elev_6b & 3u]) {    /* thief on the next stop: car waits at $F4 */
        elev_8e--;
        return;
    }
    elev_6b++;
    elev_8e = 0u;
}

/* A564..A5B9: Kop inside the car follows the car floor; down in the door window gets out */
static void in_car(uint8_t in)
{
    uint8_t cf = car_floor();
    kop_c1c = (uint8_t)((cf << 5) | 2u);
    kop_xs[cf] = kop_xs[KOP_FLOOR()];
    kop_path = BBA1[cf];
    if ((elev_8e & 0x80u) && elev_8e < 0xF0u && (in & IN_DOWN)) {
        kop_c1c -= 2u;
        kop_face &= 0x0Fu;
    }
}

/* screen change; d=+1 moving left (screen++), d=-1 moving right.  $1D runs opposite on odd floors. */
static void kop_wrap(int8_t d)
{
    if (KOP_FLOOR() & 1u)
        kop_path -= (uint8_t)d;
    else
        kop_path += (uint8_t)d;
    kop_screen += (uint8_t)d;
    obj_spawn();                               /* S_AFBB (JSR at A64D), ends with $90 &= $F3 */
    eng_events |= EV_SCREEN;
}

static void escalator_entry(void)
{
    uint8_t h, v;
    e_f = KOP_FLOOR();
    if (kop_screen != B9E3[e_f] || thief_path == kop_path)
        return;
    h = kop_c1c & 0x1Fu;
    if (kop_screen & 1u)
        h ^= 0xFFu;
    e_t = (uint8_t)(h + B8D4[e_f]);
    v = (uint8_t)(kop_xs[e_f] + (uint8_t)~e_t);
    if (v >= 2u)
        return;
    kop_jump = 0u;                             /* $19 */
    kop_latch = 0xFCu;                         /* $18 */
    kop_c1c = (uint8_t)((kop_c1c & 0xFCu) | ((frame_8f >> 2) & 3u));
    h = kop_c1c & 0x1Fu;
    if (e_f != 1u)
        h = (uint8_t)((uint8_t)~h + 3u);
    kop_xs[e_f] = (uint8_t)(h + B8D4[e_f]);
    kop_face = B8D7[e_f];
    kop_pose = 6u;
}

static void ride_tick(void)
{
    if (frame_8f & 3u)
        return;
    e_f = KOP_FLOOR();
    if (kop_face == 0xA8u)
        kop_xs[e_f]--;
    else
        kop_xs[e_f]++;
    kop_c1c++;
    if ((kop_c1c & 0x1Fu) == 0u) {
        kop_path++;
        kop_face &= 0x0Fu;
    }
}

/* One Kop pass (A5C0..A76C).  frame_90 is $90 before this frame's increment. */
static void kop_step(uint8_t in)
{
    uint8_t st, wrapped = 0u, walking = 0u, old;
    if (riding()) {
        ride_tick();
        return;
    }
    if ((kop_face & 0xC0u) == 0xC0u) {
        in_car(in);
        return;
    }
    st = kop_jump ? kop_stick : in;            /* $62 latched while in the air */
    e_f = KOP_FLOOR();
    /* --- movement (A5C0..A689) */
    if (st & IN_DOWN) {
        kop_pose = 7u;
    } else if (st & IN_LEFT) {
        kop_face = 8u;
        e_x = (uint8_t)(kop_xs[e_f] - 1u);
        kop_xs[e_f] = e_x;
        if (e_x <= ((kop_screen == 7u) ? 0x2Du : 0x2Au)) {
            if (kop_screen == 7u) {
                kop_xs[e_f] = 0x2Fu;
            } else {
                kop_xs[e_f] = 0xCFu;
                kop_wrap(1);
                wrapped = 1u;
            }
        }
        walking = 1u;
    } else if (st & IN_RIGHT) {
        kop_face = 0u;
        e_x = (uint8_t)(kop_xs[e_f] + 1u);
        if (kop_screen == 0u) {
            kop_xs[e_f] = (e_x >= 0xCBu) ? 0xC9u : e_x;
        } else if (e_x < 0xCCu) {
            kop_xs[e_f] = e_x;
        } else {
            kop_xs[e_f] = 0x2Bu;
            kop_wrap(-1);
            wrapped = 1u;
        }
        walking = 1u;
    } else {
        kop_pose = 6u;
        /* A653..A687: elevator entry (standing, up pressed, doors open, car here, x in $77..$79) */
        if (kop_screen == 4u && kop_jump == 0u && (elev_8e & 0x80u) && elev_8e < 0xF0u
                && car_floor() == KOP_FLOOR() && kop_xs[KOP_FLOOR()] >= 0x77u
                && kop_xs[KOP_FLOOR()] <= 0x79u && (in & IN_UP)) {
            kop_c1c += 2u;
            kop_face |= 0xE0u;
        }
    }
    if (walking) {
        if (!wrapped) {
            if (kop_xs[KOP_FLOOR()] & 1u) {
                kop_pose++;
                if (kop_pose >= 6u)
                    kop_pose = 1u;
            }
            if (!snd_id && kop_pose == 4u) {   /* A69C: walk step sound */
                sfx_start(2u, 2u);
                eng_events |= EV_STEP;
            }
        }
        escalator_entry();
    }
    /* --- jump (A704..A76C) */
    if (riding())
        return;
    if (kop_jump) {
        old = kop_jump;
        if ((uint8_t)(old - 6u) >= 6u || (frame_90 & 3u) == 0u) {
            kop_jump = (uint8_t)(old - 1u);
            if (kop_jump >= 9u)
                kop_c1c++;
            else
                kop_c1c--;
            if (kop_jump == 0u)
                eng_events |= EV_LAND;
        }
        kop_pose = 2u;
        if (kop_jump >= 0x10u)
            kop_stick = in;                    /* re-latched while $19 >= $10 (A735..A75F) */
    } else {
        if (!(in & IN_FIRE)) {
            kop_latch = 0u;
        } else if (!kop_latch) {
            kop_jump = 0x12u;
            kop_stick = in;
            kop_latch = 0xFFu;
            sfx_start(3u, 0x11u);              /* $17=3, $12=$11 */
            eng_events |= EV_JUMP;
        }
    }
}

/* ---------------------------------------------------------------- thief (A973..AA20) */

/* $58 bit3: nonzero = moving left (decreasing X).  Computed from the current state (the Atari
 * keeps the value of the previous frame's end; they differ only on the frame Kop crosses it). */
uint8_t thief_dir_left(void)
{
    uint8_t fb = thief_path & 0x18u, kf = kop_path & 0x18u;
    uint8_t d = (uint8_t)((fb ^ 8u) & 8u);
    if (kf == fb) {
        if (thief_path == kop_path)            /* AAA5: same floor + screen, flee from Kop's X */
            d = (thief_x < kop_xs[KOP_FLOOR()]) ? 8u : 0u;
        else
            d = (thief_screen() >= kop_screen) ? 8u : 0u;
    } else if (kf > fb)
        d ^= 8u;
    return d;
}

/* path step at a screen end; returns the new X */
static uint8_t thief_turn(int8_t d, uint8_t ywrap)
{
    if (d < 0 && thief_path == 0u)
        return 0xCAu;                          /* path would go below 0: stays 0, x = $CA */
    thief_path += (uint8_t)d;
    e_t = thief_path & 7u;
    if ((d > 0 && e_t == 0u) || (d < 0 && e_t == 7u))
        return (uint8_t)((uint8_t)~ywrap + 0xF9u);   /* floor boundary: ~Y + $F8 + 1 */
    return ywrap;
}

static void thief_step(void)
{
    uint8_t y;
    if (!(frame_90 & 1u) || thief_escaped)
        return;
    y = thief_x;
    if (!thief_dir_left()) {
        y++;
        if (y >= 0xCDu) {
            if (thief_path == 0x1Fu) {
                thief_escaped = 0x80u;
                return;
            }
            y = thief_turn((thief_path & 8u) ? 1 : -1, 0x2Bu);
        }
    } else {
        y--;
        if (y < 0x29u)
            y = thief_turn((thief_path & 8u) ? -1 : 1, 0xCFu);
    }
    thief_x = y;
    if (y & 1u)
        thief_anim = (thief_anim + 1u < 6u) ? (uint8_t)(thief_anim + 1u) : 1u;
}

/* ---------------------------------------------------------------- frame */

void engine_frame(uint8_t in)
{
    uint8_t y;
    eng_events = 0u;
    eng_sfx = 0u;
    kop_col = kop_col_next;                    /* $0D+f latched while the last frame was shown */
    /* AD0F block of the previous frame (runs after the trace sampling point) */
    if (kop_ad_pending)
        elevator_logic();
    /* A436: bonus count after a catch, one time unit per 4 frames */
    if ((bonus_on & 0x80u) && !(frame_90 & 3u)) {
        if (!game_time) {                      /* A446: next level */
            level++;
            level_start = level;
            level_restart();
            goto tail;
        }
        time_dec();
        sfx_start(1u, 1u);
        score_add((level >= 0x10u) ? 3u : ((level & 8u) ? 2u : 1u));
    }
    if (!(play_on & 0x80u))                    /* A4EC */
        goto tail;
    if (snd_id == 5u)                          /* A4F3: hit cancels the latched stick */
        kop_stick = 0u;
    if (snd_id == 6u)                          /* A4FD: dying, nothing but the tail */
        goto tail;
    e_6c = snd_id;                             /* A501 */
    /* A528..A53D: elevator phase counter (every frame, any screen), then $8F++ */
    y = (kop_screen == 4u && car_floor() == KOP_FLOOR()) ? 1u : 7u;
    e_t = elev_8e;
    if (e_t < 0x80u || e_t >= 0xF0u || (y & frame_90) == 0u) {
        elev_8e++;
        if (elev_8e == 0u)
            elev_6b++;
    }
    frame_8f++;
    /* A53F..A554: timer, every 128 frames (every 4 while hit); reaching 0 = death */
    if (!(frame_90 & ((e_6c == 5u) ? 3u : 0x7Fu))) {
        if (game_time)
            time_dec();
        if (!game_time) {
            death_start();
            goto tail;
        }
    }
    if (e_6c >= 5u)                            /* A557: frozen while hit */
        goto tail;
    kop_step(in);
    /* A76C..A786 */
    if (thief_escaped) {
        death_start();
        goto tail;
    }
    if (!(bonus_on & 0x80u) && !(kop_face & 0x80u) && kop_col)
        collide();
tail:
    kop_ad_pending = (kop_screen == 4u);
    /* A877 (A865..A875): while height >= 13 the floor above mirrors Kop's X */
    e_f = KOP_FLOOR();
    if ((kop_c1c & 0x1Fu) >= 13u && e_f < 3u)
        kop_xs[e_f + 1u] = kop_xs[e_f];
    sfx_tick();
    /* A8F8: play starts at the end of the music phrase */
    if (intro_cnt && !--intro_cnt && !(bonus_on & 0x80u) && !game_over)
        play_on = 0xFFu;
    frame_90++;                                /* A974 */
    if (play_on & 0x80u)
        thief_step();
    obj_frame();
    /* GTIA: this state is displayed during the next frame, which latches and reads it */
    kop_col_next = obj_touch();
    eng_rand();
}
