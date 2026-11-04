#ifndef TRACE_H
#define TRACE_H
/*
 * trace.h - golden-trace hook (DEBUG_TRACE builds only: .\build.ps1 -Trace).
 *
 * Protocol with tests/c_trace.mjs (all symbols global, addresses from the .noi):
 *   dbg_state  0 boot, 1 = engine initialised and waiting (tool pokes engine globals, dbg_plan,
 *              then sets dbg_go = 1), 2 = running the plan, 3 = plan finished (tool sets
 *              dbg_go = 0 -> back to 1).
 *   dbg_plan   up to TRACE_PLAN_MAX entries of (IN_* bits, count lo, count hi); count 0 ends.
 *   trace_head rows written (free-running, ROM side); trace_tail rows consumed (tool side).
 *   trace_ring TRACE_ROWS x TRACE_COLS bytes; row n lives at slot n % TRACE_ROWS.  The game
 *              stalls (no logic step) while the ring is full, so the trace is indexed by logic
 *              step, not by PPU frame.
 * Row columns = Atari addresses, in this order (same values tools/atari_trace.py prints):
 *   $90 $8F $8E $6B $2C $2D $2E $2F $1D $1E $1C $20 $0C $19 $1B $1F $11 $28 $63 $1A
 */
#ifdef DEBUG_TRACE
#include <stdint.h>

#define TRACE_ROWS     32u
#define TRACE_COLS     20u
#define TRACE_PLAN_MAX 16u

extern volatile uint8_t dbg_state, dbg_go;
extern uint8_t dbg_plan[TRACE_PLAN_MAX * 3u];
extern volatile uint8_t trace_head, trace_tail;
extern uint8_t trace_ring[TRACE_ROWS * TRACE_COLS];

void trace_wait_go(void);      /* state 1, wait for dbg_go, state 2 */
uint8_t trace_next(void);      /* 1 = next input in trace_in, 0 = plan finished */
extern uint8_t trace_in;
uint8_t trace_full(void);      /* ring full: keep calling vsync, do not step */
void trace_emit(void);         /* after engine_frame */
void trace_finish(void);       /* state 3, wait for dbg_go == 0 */
#endif
#endif
