/* Keystone Kapers sound: NES APU approximation of the POKEY effects and BGM.
 * Effects  : pulse 1 or noise (one effect at a time, like POKEY channel 1).
 * BGM      : POKEY ch3 -> pulse 2, ch4 -> triangle.  10 frames per step.
 * Tables come from tools/gen_sound.py (src/sound_data.c). Non-NES targets get empty stubs. */
#include "sound.h"

#ifndef __SDCC_sm83   /* NES (6502) */

#include "sound_data.h"

#define APU(a) (*(volatile uint8_t *)(a))
#define SQ1_VOL  APU(0x4000)
#define SQ1_SWP  APU(0x4001)
#define SQ1_LO   APU(0x4002)
#define SQ1_HI   APU(0x4003)
#define SQ2_VOL  APU(0x4004)
#define SQ2_SWP  APU(0x4005)
#define SQ2_LO   APU(0x4006)
#define SQ2_HI   APU(0x4007)
#define TRI_LIN  APU(0x4008)
#define TRI_LO   APU(0x400A)
#define TRI_HI   APU(0x400B)
#define NOI_VOL  APU(0x400C)
#define NOI_PER  APU(0x400E)
#define NOI_LEN  APU(0x400F)
#define APU_STAT APU(0x4015)
#define APU_FRM  APU(0x4017)

#define LEN_HALT_CONST 0x30   /* length counter halted + constant volume */

static uint8_t eff_id;     /* 0 = idle */
static uint8_t eff_pos;    /* next step index */
static uint8_t eff_wait;   /* frames left in the current step */
static uint8_t eff_hi;     /* last pulse high byte written (avoid phase resets) */
static uint8_t bgm_on;
static uint8_t bgm_idx;    /* 1..SND_BGM_LEN-1 */
static uint8_t bgm_f;      /* frame within the step */

static void eff_silence(void)
{
    SQ1_VOL = LEN_HALT_CONST;
    NOI_VOL = LEN_HALT_CONST;
}

static void eff_load(void)
{
    uint8_t d, v, ch;
    d = snd_step_dur[eff_pos];
    if (d == SND_STEP_LOOP) {
        eff_pos = snd_step_lo[eff_pos];
        d = snd_step_dur[eff_pos];
    }
    if (d == SND_STEP_END) {
        eff_silence();
        eff_id = 0;
        return;
    }
    eff_wait = d;
    v = snd_step_vol[eff_pos];
    ch = snd_eff_chan[eff_id];
    if (ch == SND_CH_PULSE) {
        uint8_t h = snd_step_hi[eff_pos] | 0xF8;
        SQ1_VOL = snd_eff_cfg[eff_id] | LEN_HALT_CONST | v;
        SQ1_LO = snd_step_lo[eff_pos];
        if (h != eff_hi) {
            SQ1_HI = h;
            eff_hi = h;
        }
    } else {
        NOI_VOL = LEN_HALT_CONST | v;
        NOI_PER = snd_eff_cfg[eff_id] | snd_step_lo[eff_pos];
    }
    eff_pos++;
}

void snd_init(void)
{
    APU_FRM = 0x40;            /* 4-step frame counter, IRQ off */
    APU_STAT = 0x00;
    SQ1_SWP = 0x08;            /* sweep off (and no low-period muting) */
    SQ2_SWP = 0x08;
    eff_silence();
    SQ2_VOL = LEN_HALT_CONST;
    TRI_LIN = 0x80;
    NOI_LEN = 0xF8;
    APU_STAT = 0x0F;           /* pulse 1, pulse 2, triangle, noise */
    eff_id = 0;
    bgm_on = 0;
}

void snd_play(uint8_t id)
{
    eff_silence();
    eff_id = 0;
    if (id == 0 || id > SND_NUM_EFFECTS) return;
    eff_id = id;
    eff_pos = snd_eff_start[id];
    eff_hi = 0;                /* force the first pulse write to latch the timer */
    eff_load();
}

void snd_bgm(uint8_t on)
{
    if (on) {
        if (!bgm_on) {
            bgm_on = 1;
            bgm_idx = 1;
            bgm_f = 0;
        }
    } else {
        bgm_on = 0;
        SQ2_VOL = LEN_HALT_CONST;
        TRI_LIN = 0x80;
        TRI_HI = 0xF8;         /* reload the linear counter with 0 -> silent */
    }
}

void snd_tick(void)
{
    if (eff_id) {
        if (--eff_wait == 0) eff_load();
    }
    if (bgm_on) {
        uint8_t i = bgm_idx;
        if (bgm_f == 0) {
            if (snd_bgm_t_hi[i] == SND_BGM_REST) {
                TRI_LIN = 0x80;
                TRI_HI = 0xF8;
            } else {
                TRI_LIN = 0xFF;
                TRI_LO = snd_bgm_t_lo[i];
                TRI_HI = snd_bgm_t_hi[i] | 0xF8;
            }
            if (snd_bgm_p_hi[i] != SND_BGM_REST) {
                SQ2_LO = snd_bgm_p_lo[i];
                SQ2_HI = snd_bgm_p_hi[i] | 0xF8;
            }
        }
        if (snd_bgm_p_hi[i] == SND_BGM_REST)
            SQ2_VOL = LEN_HALT_CONST;
        else
            SQ2_VOL = 0x80 | LEN_HALT_CONST | snd_bgm_env[bgm_f];
        if (++bgm_f == SND_BGM_STEP) {
            bgm_f = 0;
            if (++bgm_idx >= SND_BGM_LEN) bgm_idx = 1;
        }
    }
}

#else  /* Game Boy: the real driver is src/gbc/sound_gbc.c (build_gbc.ps1 does not compile this file) */

void snd_init(void) {}
void snd_play(uint8_t id) { (void)id; }
void snd_bgm(uint8_t on) { (void)on; }
void snd_tick(void) {}

#endif
