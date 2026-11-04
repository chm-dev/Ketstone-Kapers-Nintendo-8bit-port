#ifndef OBSTACLE_H
#define OBSTACLE_H
/*
 * obstacle.h - per-floor object slots (obstacles, pickups, the thief on Kop's floor), shared C.
 * Port of tools/obstacle_model.py (motion, verified vs tests/golden/obst_lv*.txt) and of the spawn
 * S_AFC2 / thief-slot AA24 code; docs/ATARI_RE_SPEC.md 7, 9, 9b.  Slots always describe Kop's screen.
 */
#include <stdint.h>

extern uint8_t obj_t[4];      /* $75+f type: 0 none, 1-5 thief frame, 2 just collected, 6/7 radio,
                                 8 ball, 9 cart, 10/11 plane, $0F suitcase, $10 money bag */
extern uint8_t obj_x[4];      /* $30+f HPOS of the first copy ($20..$D9, wraps) */
extern uint8_t obj_fl[4];     /* $34+f bit3 = moves right (thief: moves left), bits 0-2 copy layout */
extern uint8_t obj_h[4];      /* $71+f height offset ($1A = on the floor; plane $0A) */
extern uint8_t obj_8d;        /* $8D ball bounce phase (one counter for every ball) */
extern uint8_t obj_5f;        /* $5F ball amplitude of the last ball processed */
extern uint8_t obj_6e;        /* $6E type a cleared slot gets (0, the radio type during a radio hit) */
extern uint8_t obj_6f;        /* $6F radio copies alive: bit0 $98, bit1 $78, bit2 $58 */
extern uint8_t obj_rx, obj_rfl; /* $9F/$A0 radio X / flags restored after a radio hit */
extern uint8_t pickup_scr[4]; /* $85+f screen of floor f's pickup ($0F/$10 once collected) */
extern uint8_t obj_cx[3];     /* obj_copies(): HPOS of each drawn copy */

void obj_reset(void);         /* empty slots (power-on state) */
void obj_spawn(void);         /* S_AFBB/AFC2: rebuild the 4 slots for kop_screen (ends with $90 &= $F3) */
void obj_pickups(void);       /* AFA9: random pickup screen per floor */
void obj_floor(uint8_t f);    /* AACD..ABC7: one floor's obstacle step (frame_90 = $90 after ++) */
void obj_frame(void);         /* AA24..ABC7: thief slot + obstacle step, floors 3..0 */
uint8_t obj_copies(uint8_t f);/* copies of slot f (DLI B2C3-B30F) into obj_cx[], returns the count */
uint8_t obj_touch(void);      /* Kop box vs his floor's slot: the GTIA collision of this frame */
uint8_t obj_frame_of(uint8_t t); /* type -> sprite frame index (SPR_F_*), 0xFF = none */

/* Opaque-pixel box of each sprite frame (src/spr_data.h SPR_F_* order), from
 * python tools/kk_game_model.py --boxes: rows top/bottom relative to the pivot, columns 0..7. */
extern const int8_t obj_box[20][4];
#endif
