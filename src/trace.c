/* trace.c - golden-trace hook, see trace.h.  Compiles to nothing without DEBUG_TRACE. */
#include "platform.h"
#include "trace.h"

#ifdef DEBUG_TRACE
#include "engine.h"

volatile uint8_t dbg_state, dbg_go;
uint8_t dbg_plan[TRACE_PLAN_MAX * 3u];
volatile uint8_t trace_head, trace_tail;
uint8_t trace_ring[TRACE_ROWS * TRACE_COLS];
uint8_t trace_in;

static uint8_t plan_i;
static uint16_t plan_left;
static uint8_t *row;

void trace_wait_go(void)
{
    trace_head = 0u;
    dbg_state = 1u;
    while (!dbg_go)
        vsync();
    trace_tail = 0u;
    trace_head = 0u;
    plan_i = 0u;
    plan_left = 0u;
    dbg_state = 2u;
}

uint8_t trace_next(void)
{
    while (plan_left == 0u) {
        if (plan_i >= TRACE_PLAN_MAX * 3u)
            return 0u;
        plan_left = dbg_plan[plan_i + 1u] | ((uint16_t)dbg_plan[plan_i + 2u] << 8);
        if (plan_left == 0u)
            return 0u;
        trace_in = dbg_plan[plan_i];
        plan_i += 3u;
    }
    plan_left--;
    return 1u;
}

uint8_t trace_full(void)
{
    return (uint8_t)(trace_head - trace_tail) >= TRACE_ROWS;
}

void trace_emit(void)
{
    row = &trace_ring[(uint16_t)(trace_head & (TRACE_ROWS - 1u)) * TRACE_COLS];
    row[0] = frame_90;
    row[1] = frame_8f;
    row[2] = elev_8e;
    row[3] = elev_6b;
    row[4] = kop_xs[0];
    row[5] = kop_xs[1];
    row[6] = kop_xs[2];
    row[7] = kop_xs[3];
    row[8] = kop_path;
    row[9] = kop_screen;
    row[10] = kop_c1c;
    row[11] = kop_pose;
    row[12] = kop_face;
    row[13] = kop_jump;
    row[14] = thief_x;
    row[15] = thief_path;
    row[16] = thief_screen();
    row[17] = game_time;
    row[18] = thief_anim;
    row[19] = thief_escaped;
    trace_head++;                              /* publish after the row is complete */
}

void trace_finish(void)
{
    dbg_state = 3u;
    while (dbg_go)
        vsync();
}
#else
typedef int trace_c_is_empty_without_debug_trace;
#endif
