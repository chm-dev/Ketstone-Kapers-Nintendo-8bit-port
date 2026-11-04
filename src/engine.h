#ifndef ENGINE_H
#define ENGINE_H
/*
 * engine.h - Keystone Kapers game logic, shared by every target (no platform calls).
 * 1:1 port of tools/kk_model.py (Kop walk/jump/duck/escalators/elevator, thief, timer),
 * verified against the tests/golden traces with the DEBUG_TRACE build (tests/run_c_trace.ps1).
 * Atari zero-page names are given next to each variable (docs/ATARI_RE_SPEC.md 4-6).
 *
 * World coordinates only: X is the Atari per-screen unit ($2C..$CB visible, 1 unit = 1 px),
 * floor 0..3 (0 = ground), screen 0..7 (0 = right end).  The camera (pillarbox, sprite
 * offsets) lives in the renderer (main.c).
 */
#include <stdint.h>

/* Engine input bits (one byte per frame; the renderer maps the pad to these). */
#define IN_UP    0x01u
#define IN_DOWN  0x02u
#define IN_LEFT  0x04u
#define IN_RIGHT 0x08u
#define IN_FIRE  0x10u

/* Kop state */
extern uint8_t kop_xs[4];     /* $2C+floor  Kop X per floor */
extern uint8_t kop_path;      /* $1D  floor*8 + path index (odd floors mirrored) */
extern uint8_t kop_screen;    /* $1E  0..7, 0 = right end of the store */
extern uint8_t kop_face;      /* $0C  0 right, 8 left; $80/$A8 riding an escalator; |$E0 in the elevator car */
extern uint8_t kop_pose;      /* $20  1..5 walk, 2 jump, 6 stand, 7 duck */
extern uint8_t kop_jump;      /* $19  jump countdown ($12 at take-off) */
extern uint8_t kop_c1c;       /* $1C  bits 0-4 height (jump / escalator step), bits 5-7 floor marker */
extern uint8_t kop_latch;     /* $18  trigger latch */
extern uint8_t kop_stick;     /* $62  stick latched at take-off (IN_* bits) */
extern uint8_t elev_8e;       /* $8E  elevator phase counter */
extern uint8_t elev_6b;       /* $6B  elevator trip counter: car floor = [0,1,2,1][$6B&3] */
extern uint8_t kop_ad_pending;/* AD0F elevator block runs at the start of the next frame */

/* Thief and timer */
extern uint8_t thief_x;       /* $1B */
extern uint8_t thief_path;    /* $1F  bits 3-4 floor, bits 0-2 index (odd floors mirrored) */
extern uint8_t thief_anim;    /* $63  1..5 */
extern uint8_t thief_escaped; /* $1A bit7: thief reached the roof end */
extern uint8_t game_time;     /* $28  time left, BCD ($50 at level start) */

/* Frame counters */
extern uint8_t frame_90;      /* $90  frame counter (+1 per frame at A974; &$F3 on a screen change) */
extern uint8_t frame_8f;      /* $8F  frame counter (+1 per frame at A53D, before the Kop logic) */

/* Events for the renderer / sound (cleared at the start of every engine_frame). */
#define EV_SCREEN  0x01u      /* Kop changed screen this frame (flip-screen redraw) */
#define EV_JUMP    0x02u      /* jump started ($17=3) */
#define EV_LAND    0x04u      /* jump ended ($19 reached 0) */
#define EV_STEP    0x08u      /* walk step sound: pose became 4 ($17=2) */
extern uint8_t eng_events;

#define KOP_FLOOR()   ((uint8_t)((kop_path >> 3) & 3u))
#define KOP_X()       (kop_xs[KOP_FLOOR()])
#define THIEF_FLOOR() ((uint8_t)((thief_path >> 3) & 3u))
uint8_t thief_screen(void);   /* $11: thief path folded to a screen number 0..7 */
uint8_t car_floor(void);      /* elevator car floor 0..2 */

void engine_init(void);           /* level start state (A27A / $B9BB table) */
void engine_frame(uint8_t in);    /* one main-loop pass with this frame's input (IN_* bits) */

#endif
