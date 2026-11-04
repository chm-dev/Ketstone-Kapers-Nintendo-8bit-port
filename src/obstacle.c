/*
 * obstacle.c - per-floor object slots: spawn (S_AFC2), thief slot (AA24), obstacle motion
 * (AACD..ABC7, = tools/obstacle_model.py step()), copy layout and Kop collision boxes.
 * Shared C, no platform calls.  Atari addresses in comments.
 */
#include "engine.h"

uint8_t obj_t[4], obj_x[4], obj_fl[4], obj_h[4];
uint8_t obj_8d, obj_5f, obj_6e, obj_6f, obj_rx, obj_rfl;
uint8_t pickup_scr[4];
uint8_t obj_cx[3];

/* ROM tables */
static const uint8_t B9A7[8] = { 0x01u, 0x01u, 0x01u, 0x03u, 0x03u, 0x07u, 0x07u, 0x0Fu }; /* ball hold mask */
static const uint8_t B9AF[8] = { 1u, 1u, 2u, 3u, 3u, 5u, 6u, 6u };                         /* pickup screens */
static const uint8_t BEF1[8] = { 0x00u, 0xA0u, 0x80u, 0x60u, 0x05u, 0x00u, 0x07u, 0x06u }; /* radio mask by mode */
/* copy mode by type and tier ($BC00 + $B8F5[t]): radio, ball, cart, plane */
static const uint8_t COPY_MODE[4][4] = {
    { 0u, 4u, 6u, 6u }, { 0u, 0u, 4u, 4u }, { 0u, 0u, 4u, 0u }, { 0u, 0u, 0u, 0u } };
static const uint8_t GATE_THR[4] = { 1u, 0u, 2u, 3u };   /* $BBA2[t] for t = 7..10 */
/* bit0 of the code bytes $AAEE+i (i = $90>>1), the radio flicker "noise", packed LSB first */
static const uint8_t AAEE_BITS[16] = {
    0x8Du, 0x98u, 0x82u, 0x88u, 0x44u, 0x42u, 0x49u, 0x02u,
    0xE4u, 0x88u, 0x3Du, 0x15u, 0x94u, 0x91u, 0x4Du, 0x00u };
/* type -> sprite frame (src/spr_data.h spr_obj_type) */
static const uint8_t TYPE_FRAME[17] = {
    0xFFu, 7u, 8u, 9u, 10u, 11u, 12u, 13u, 14u, 15u, 16u, 17u, 0xFFu, 0xFFu, 0xFFu, 18u, 19u };
/* Kop pose $20 -> frame (spr_kop_pose) */
static const uint8_t POSE_FRAME[8] = { 5u, 0u, 1u, 2u, 3u, 4u, 5u, 6u };

const int8_t obj_box[20][4] = {
    { -19,   0, 0, 7 },   /*  0 KOP_WALK1 */
    { -19,  -4, 0, 7 },   /*  1 KOP_WALK2 (also the jump pose) */
    { -19,   0, 0, 7 },   /*  2 KOP_WALK3 */
    { -19,   0, 1, 6 },   /*  3 KOP_WALK4 */
    { -19,   0, 1, 6 },   /*  4 KOP_WALK5 */
    { -19,   0, 1, 6 },   /*  5 KOP_STAND */
    { -16,   0, 0, 7 },   /*  6 KOP_DUCK */
    { -19,   0, 0, 6 },   /*  7 THIEF1 */
    { -19,  -2, 0, 7 },   /*  8 THIEF2 */
    { -19,   0, 0, 6 },   /*  9 THIEF3 */
    { -19,   0, 1, 6 },   /* 10 THIEF4 */
    { -19,   0, 1, 6 },   /* 11 THIEF5 */
    { -11,   0, 0, 7 },   /* 12 RADIO_A */
    { -12,   0, 0, 7 },   /* 13 RADIO_B */
    {  -6,  -1, 1, 6 },   /* 14 BALL */
    {  -8,   0, 0, 7 },   /* 15 CART */
    {  -8,  -1, 0, 7 },   /* 16 PLANE_A */
    {  -8,  -1, 0, 7 },   /* 17 PLANE_B */
    {  -8,   0, 0, 7 },   /* 18 SUITCASE */
    {  -9,   0, 1, 7 },   /* 19 MONEYBAG */
};

/* scratch (SDCC: flat statics) */
static uint8_t o_a, o_f, o_t, o_n, o_v;

uint8_t obj_frame_of(uint8_t t)
{
    return (t < 17u) ? TYPE_FRAME[t] : 0xFFu;
}

void obj_reset(void)
{
    for (o_f = 0u; o_f < 4u; o_f++) {
        obj_t[o_f] = 0u;
        obj_x[o_f] = 1u;
        obj_fl[o_f] = 0u;
        obj_h[o_f] = 0x1Au;
    }
    obj_8d = 0u;
    obj_5f = 0u;
    obj_6e = 0u;
    obj_6f = 0u;
    obj_rx = 0u;
    obj_rfl = 0u;
}

void obj_pickups(void)                       /* AFA9..AFB7 ($A429 code bytes as noise -> RNG) */
{
    for (o_f = 0u; o_f < 4u; o_f++)
        pickup_scr[o_f] = B9AF[eng_rand() & 7u];
}

/* S_AEEB: 1 = type enabled at this level; o_a = speed / tier index */
static uint8_t gate(uint8_t thr)
{
    o_a = level >> 2;
    if ((level & 3u) >= thr)
        return 1u;
    if (!o_a)
        return 0u;
    o_a--;
    return 1u;
}

/* ---------------------------------------------------------------- spawn (AFC2..B0CE) */
void obj_spawn(void)
{
    uint8_t f = 4u, t, fl, xr, xl;
    while (f--) {
        if (kop_screen == 0u)
            t = 0u;
        else if (kop_screen == pickup_scr[f])
            t = (uint8_t)(0x0Fu + (f & 1u));
        else {
            t = (uint8_t)(f + (kop_screen & 3u) + 7u);
            if (t >= 0x0Bu)
                t -= 4u;
            if (f == 3u && !(t & 1u))          /* ROR / SBC #0 / ROL: even types -1 on floor 3 */
                t--;
        }
        obj_t[f] = t;
        obj_fl[f] = 0u;
        obj_h[f] = 0x1Au;
        if (!t)
            continue;                          /* X keeps its old value (B013) */
        if (t >= 0x0Fu) {
            obj_x[f] = 0x78u;                  /* pickup */
            continue;
        }
        /* copy mode by tier (B01D..B040) */
        o_t = (uint8_t)(t - 7u);
        o_a = level >> 2;
        if (o_a) {
            if ((level & 3u) < GATE_THR[o_t])
                o_a--;
            if (o_a > 3u)
                o_a = 3u;
        }
        fl = COPY_MODE[o_t][o_a];
        if (kop_screen == 4u && t == 7u) {     /* B042..B05E: radio on the elevator screen */
            if (level >= 5u)
                fl = 4u;
            else
                obj_t[f] = 0u;
        }
        fl |= (uint8_t)(kop_face & 0x0Cu);     /* start in Kop's walking direction */
        obj_fl[f] = fl;
        t = obj_t[f];
        xr = 0x39u;
        xl = 0xBAu;
        if (t == 7u) {                         /* B0B1: radios */
            obj_6f = BEF1[fl & 7u];
            obj_x[f] = (fl & 7u) ? 0x58u : 0x78u;
            continue;
        }
        if ((t == 9u && ((level >= 6u && level < 0x0Au) || level >= 0x0Eu))
                || (t == 10u && level >= 7u)) {   /* B088: random direction (POKEY RANDOM bit3) */
            o_v = eng_rand() & 8u;             /* $95 is always 0 here (spec 9b) */
            if (o_v != fl) {
                fl = o_v;
                obj_fl[f] = fl;
                xr = 0x7Au;
                xl = 0x7Au;
            }
        }
        if (fl & 8u)
            obj_x[f] = xr;
        else
            obj_x[f] = (fl & 4u) ? 0x7Cu : xl;
    }
    obj_8d = 0u;                               /* B006 */
    kop_col = 0u;                              /* B00A: $0D+f = 0 */
    kop_col_next = 0u;
    frame_90 &= 0xF3u;                         /* B0CE [V kop_b frame 79] */
}

/* ---------------------------------------------------------------- motion (AACD..ABC7) */
static void obj_clear(uint8_t f)              /* AAEE */
{
    obj_t[f] = obj_6e;
    if (!obj_6e)
        obj_x[f] = 1u;
}

void obj_floor(uint8_t f)
{
    uint8_t t = obj_t[f], y, per;
    if (t < 6u) {
        obj_clear(f);
        return;
    }
    if (t < 8u) {                              /* radio: stationary, flickers between 6 and 7 */
        if (gate(1u))
            obj_t[f] = (uint8_t)(6u + ((AAEE_BITS[frame_90 >> 4] >> ((frame_90 >> 1) & 7u)) & 1u));
        else
            obj_clear(f);
        return;
    }
    if (t == 8u) {                             /* ball (AAFD..AB5B) */
        if (level < 4u || level >= 0x10u)
            o_a = 3u;
        else if (level < 8u)
            o_a = 0x0Cu;
        else {
            gate(0u);
            o_a = (o_a & 1u) ? 3u : 0x0Cu;
        }
        obj_5f = o_a;
        per = (uint8_t)((o_a + 8u) << 1);
        y = (uint8_t)(obj_8d + 1u);
        if (y >= per)
            y = 0u;
        o_v = (uint8_t)(y - o_a);
        o_t = 0u;
        if (o_v < 0x10u) {
            if (o_v >= 8u)
                o_v ^= 0x0Fu;
            o_t = B9A7[o_v] & frame_90;        /* hold near the top */
        }
        if (!o_t) {
            obj_8d = y;
            if (y < (uint8_t)(per >> 1))
                obj_h[f]--;
            else
                obj_h[f]++;
        }
        o_n = frame_90 & 1u;
    } else if (t == 9u) {                      /* cart */
        if (!gate(2u)) {
            obj_clear(f);
            return;
        }
        if (level >= 0x0Eu)
            o_n = 4u;
        else if (o_a >= 3u)
            o_n = 1u;
        else
            o_n = (o_a & 1u) ? 2u : 1u;
    } else if (t < 12u) {                      /* plane: 16 px above the floor objects */
        obj_h[f] = 0x0Au;
        obj_t[f] = (uint8_t)(0x0Au + ((frame_90 & 2u) >> 1));
        if (!gate(3u)) {
            obj_clear(f);
            return;
        }
        o_n = (uint8_t)(((o_a > 3u) ? 3u : o_a) + 1u);
    } else
        return;                                /* pickups do not move */
    while (o_n) {                              /* AB9E */
        o_n--;
        if (snd_id >= 5u || !(play_on & 0x80u))
            break;
        y = (uint8_t)(obj_x[f] + ((obj_fl[f] & 8u) ? 1u : 0xFFu));
        if (y == 0x18u)
            y = 0xD9u;
        if (y >= 0xDAu)
            y = 0x20u;
        obj_x[f] = y;
    }
}

/* AA24..ABC7, floors 3..0.  frame_90 is $90 after this frame's increment. */
void obj_frame(void)
{
    uint8_t f = 4u, tf = THIEF_FLOOR(), ts = thief_screen();
    while (f--) {
        if (f == tf && ts == kop_screen) {
            if (thief_path == kop_path || kop_screen == 0u || kop_screen == 7u) {
                /* AAA5: the thief takes the slot (P0, catchable when on Kop's floor) */
                obj_t[f] = thief_anim;
                obj_x[f] = thief_x;
                obj_fl[f] = thief_dir_left();
                obj_h[f] = 0x1Au;
                continue;
            }
            kop_xs[f] = thief_x;               /* AA5A: drawn with P3, X in Kop's slot of that floor */
        }
        obj_floor(f);
    }
}

/* ---------------------------------------------------------------- copies + collision */
uint8_t obj_copies(uint8_t f)
{
    o_v = obj_x[f];
    obj_cx[0] = o_v;
    switch (obj_fl[f] & 7u) {
    case 4u:                                   /* 2nd copy at X+$40, wraps when X >= $A0 */
        if (o_v >= 0xA0u)
            obj_cx[1] = (uint8_t)(o_v - ((obj_fl[f] & 8u) ? 0x7Au : 0x81u));
        else
            obj_cx[1] = (uint8_t)(o_v + 0x40u);
        return 2u;
    case 6u:                                   /* three radios X, X+$20, X+$40 */
        obj_cx[1] = (uint8_t)(o_v + 0x20u);
        obj_cx[2] = (uint8_t)(o_v + 0x40u);
        return 3u;
    case 7u:
        obj_cx[1] = (uint8_t)(o_v + 0x20u);
        return 2u;
    default:
        return 1u;
    }
}

/* Box test of Kop (P3) against the object slot of his floor; replaces the GTIA P3-P0/P1
 * collision ($0D+f, mask $0B).  Checked against tests/golden/ball1.txt by tools/kk_game_model.py. */
static int8_t k_t, k_b;
static uint8_t k_l, k_r;
uint8_t obj_touch(void)
{
    uint8_t f = KOP_FLOOR(), fr, n, i, l, r;
    int8_t d, t, b;
    fr = obj_frame_of(obj_t[f]);
    if (fr == 0xFFu)
        return 0u;
    o_a = POSE_FRAME[kop_pose & 7u];
    d = (int8_t)(kop_c1c & 0x1Fu);
    k_t = (int8_t)(obj_box[o_a][0] - d);
    k_b = (int8_t)(obj_box[o_a][1] - d);
    if (kop_face & 8u) {
        k_l = (uint8_t)(kop_xs[f] + 7u - (uint8_t)obj_box[o_a][3]);
        k_r = (uint8_t)(kop_xs[f] + 7u - (uint8_t)obj_box[o_a][2]);
    } else {
        k_l = (uint8_t)(kop_xs[f] + (uint8_t)obj_box[o_a][2]);
        k_r = (uint8_t)(kop_xs[f] + (uint8_t)obj_box[o_a][3]);
    }
    d = (int8_t)(obj_h[f] - 0x1Au);
    t = (int8_t)(obj_box[fr][0] + d);
    b = (int8_t)(obj_box[fr][1] + d);
    if (t > k_b || b < k_t)
        return 0u;
    n = obj_copies(f);
    for (i = 0u; i < n; i++) {
        if (obj_fl[f] & 8u) {
            l = (uint8_t)(obj_cx[i] + 7u - (uint8_t)obj_box[fr][3]);
            r = (uint8_t)(obj_cx[i] + 7u - (uint8_t)obj_box[fr][2]);
        } else {
            l = (uint8_t)(obj_cx[i] + (uint8_t)obj_box[fr][2]);
            r = (uint8_t)(obj_cx[i] + (uint8_t)obj_box[fr][3]);
        }
        if (l <= k_r && r >= k_l)
            return 1u;
    }
    return 0u;
}
