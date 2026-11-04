/*
 * engine.c - Keystone Kapers game logic (shared C, no platform calls).
 * Line-by-line port of tools/kk_model.py; Atari addresses in comments.  Keep it literal: the
 * golden traces (tests/golden) are matched frame-exactly by tests/run_c_trace.ps1.
 */
#include "engine.h"

/* ROM tables (docs/ATARI_RE_SPEC.md 6b) */
static const uint8_t B8D4[4] = { 0x90u, 0x65u, 0x90u, 0xA8u }; /* escalator base X per floor */
static const uint8_t B8D7[4] = { 0xA8u, 0x80u, 0xA8u, 0x6Eu }; /* $0C while riding (A8 left, 80 right) */
static const uint8_t B9E3[4] = { 0x07u, 0x00u, 0x07u, 0xE0u }; /* screen holding floor f's escalator */
static const uint8_t BBA1[4] = { 0x04u, 0x0Bu, 0x14u, 0x0Bu }; /* $1D per elevator car floor */
static const uint8_t BBA2[4] = { 0x0Bu, 0x14u, 0x0Bu, 0x04u }; /* thief $1F that holds the car */

uint8_t kop_xs[4];
uint8_t kop_path, kop_screen, kop_face, kop_pose, kop_jump, kop_c1c, kop_latch, kop_stick;
uint8_t elev_8e, elev_6b, kop_ad_pending;
uint8_t thief_x, thief_path, thief_anim, thief_escaped, game_time;
uint8_t frame_90, frame_8f;
uint8_t eng_events;

/* scratch shared by the step functions (SDCC: flat statics, no deep stack use) */
static uint8_t e_f, e_x, e_t;

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

void engine_init(void)
{
    /* level init A27A / AF98: $B9BB table -> $1B=$7A $1C=0 $1D=0 $1E=0 $1F=$0B $20=6, $2C=$7A, $28=$50 */
    kop_xs[0] = 0x7Au; kop_xs[1] = 0u; kop_xs[2] = 0u; kop_xs[3] = 0u;
    kop_path = 0u; kop_screen = 0u; kop_face = 0u; kop_pose = 6u;
    kop_jump = 0u; kop_c1c = 0u; kop_latch = 0u; kop_stick = 0u;
    elev_8e = 0u; elev_6b = 0u; kop_ad_pending = 0u;      /* DECISIONS_PENDING D4 */
    thief_x = 0x7Au; thief_path = 0x0Bu; thief_anim = 3u; thief_escaped = 0u;
    game_time = 0x50u;
    frame_90 = 0u; frame_8f = 0u;
    eng_events = 0u;
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
    /* HOOK (obstacle step): per-floor object slot rebuild S_AFBB/AFC2 goes here, before the
     * $90 AND below (B0CE is its tail); engine_init() needs the same rebuild (AFC2 path). */
    frame_90 &= 0xF3u;                        /* S_AFBB tail B0CE (JSR at A64D) [V kop_b frame 79] */
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
        if (!wrapped && (kop_xs[KOP_FLOOR()] & 1u)) {
            kop_pose++;
            if (kop_pose >= 6u)
                kop_pose = 1u;
            if (kop_pose == 4u)
                eng_events |= EV_STEP;         /* $17=2 walk step */
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
            eng_events |= EV_JUMP;             /* $17=3 */
        }
    }
}

/* ---------------------------------------------------------------- thief + timer (A973..AA20) */

/* $58 bit3: nonzero = moving left (decreasing X) */
static uint8_t thief_dir_left(void)
{
    uint8_t fb = thief_path & 0x18u, kf = kop_path & 0x18u;
    uint8_t d = (uint8_t)((fb ^ 8u) & 8u);
    if (kf == fb)
        d = (thief_screen() >= kop_screen) ? 8u : 0u;
    else if (kf > fb)
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

static void timer_tick(void)
{
    /* A537..A554: $28 BCD -1 when ($90-1)&$7F == 0 (every 128 frames) */
    if (((uint8_t)(frame_90 - 1u) & 0x7Fu) == 0u && game_time) {
        if (game_time & 0x0Fu)
            game_time--;
        else
            game_time = (uint8_t)(((game_time - 0x10u) & 0xF0u) | 9u);
    }
}

/* ---------------------------------------------------------------- frame */

void engine_frame(uint8_t in)
{
    uint8_t y;
    eng_events = 0u;
    /* AD0F block of the previous frame (runs after the trace sampling point) */
    if (kop_ad_pending)
        elevator_logic();
    /* A528..A53D: elevator phase counter (every frame, any screen), then $8F++ */
    y = (kop_screen == 4u && car_floor() == KOP_FLOOR()) ? 1u : 7u;
    e_t = elev_8e;
    if (e_t < 0x80u || e_t >= 0xF0u || (y & frame_90) == 0u) {
        elev_8e++;
        if (elev_8e == 0u)
            elev_6b++;
    }
    frame_8f++;
    /* HOOK (collision step): a hit freezes Kop 36 frames ($17=5, 9 x 4): skip kop_step() then. */
    kop_step(in);
    /* HOOK (collision step): resolution A77A..A841 (thief catch, hit, death, pickup) goes here.
     * Note the Atari also writes the thief's / object's X into $2C+floor when it is on Kop's
     * screen (seen as $2D in elev_a/b); kop_xs[] here holds Kop only. */
    kop_ad_pending = (kop_screen == 4u);
    /* A877: while height >= 13 the floor above mirrors Kop's X */
    e_f = KOP_FLOOR();
    if ((kop_c1c & 0x1Fu) >= 13u && e_f < 3u)
        kop_xs[e_f + 1u] = kop_xs[e_f];
    frame_90++;                                /* A974 */
    thief_step();
    timer_tick();
}
