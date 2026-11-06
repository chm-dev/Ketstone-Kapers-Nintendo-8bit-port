/*
 * sound_gbc.c - src/sound.h on the Game Boy APU, same tables as the NES driver (src/sound_data.c,
 * tools/gen_sound.py); the GB register values come from tools/gen_gbc_assets.py (gbc_snd_*, gbc_bgm_*).
 * Mapping (NES -> GB, DECISIONS_PENDING C-log):
 *   effects, pulse  : pulse 1 -> CH1 (duty bits identical: NES $4000 bits 6-7 = NR11 bits 6-7)
 *   effects, noise  : noise   -> CH4 (nearest NR43 to the NES period; periodic mode -> 7-bit LFSR)
 *   BGM POKEY ch3   : pulse 2 -> CH2, 50 % duty, per-frame envelope snd_bgm_env (retrigger on change)
 *   BGM POKEY ch4   : triangle -> CH3 wave with a 32-step triangle table, fixed level
 * A GB volume change needs a retrigger (NRx2 then NRx4 bit 7); volume 0 turns the DAC off.
 */
#include "platform.h"
#include <stdint.h>

#include "sound.h"
#include "sound_data.h"
#include "gbc_data.h"

static uint8_t eff_id;
static uint8_t eff_pos;
static uint8_t eff_wait;
static uint8_t bgm_on;
static uint8_t bgm_idx;
static uint8_t bgm_f;
static uint8_t bgm_vol;
static uint8_t s_d, s_v, s_i;
static volatile uint8_t busy;  /* set while snd_play/snd_bgm rewrite the state: the VBL tick skips */

static const uint8_t wave_tri[16] = {
    0x01u, 0x23u, 0x45u, 0x67u, 0x89u, 0xABu, 0xCDu, 0xEFu,
    0xFEu, 0xDCu, 0xBAu, 0x98u, 0x76u, 0x54u, 0x32u, 0x10u };

static void eff_silence(void)
{
    NR12_REG = 0u;              /* DAC off = channel off */
    NR42_REG = 0u;
}

static void eff_load(void)
{
    s_d = snd_step_dur[eff_pos];
    if (s_d == SND_STEP_LOOP) {
        eff_pos = snd_step_lo[eff_pos];
        s_d = snd_step_dur[eff_pos];
    }
    if (s_d == SND_STEP_END) {
        eff_silence();
        eff_id = 0u;
        return;
    }
    eff_wait = s_d;
    s_v = (uint8_t)(snd_step_vol[eff_pos] << 4);
    if (snd_eff_chan[eff_id] == SND_CH_PULSE) {
        NR11_REG = snd_eff_cfg[eff_id] & 0xC0u;
        NR12_REG = s_v;
        NR13_REG = gbc_snd_a[eff_pos];
        NR14_REG = (uint8_t)(0x80u | gbc_snd_b[eff_pos]);
    } else {
        NR42_REG = s_v;
        NR43_REG = gbc_snd_a[eff_pos];
        NR44_REG = 0x80u;
    }
    eff_pos++;
}

void snd_init(void)
{
    NR52_REG = 0x80u;           /* APU on */
    NR50_REG = 0x77u;
    NR51_REG = 0xFFu;
    NR10_REG = 0u;              /* no sweep */
    NR11_REG = 0x80u;
    NR21_REG = 0x80u;           /* BGM pulse: 50 % */
    NR12_REG = 0u;
    NR22_REG = 0u;
    NR42_REG = 0u;
    NR30_REG = 0u;              /* wave DAC off while loading the table */
    for (s_i = 0u; s_i < 16u; s_i++)
        AUD3WAVE[s_i] = wave_tri[s_i];
    NR31_REG = 0u;
    NR32_REG = 0x20u;           /* wave level 100 % */
    eff_id = 0u;
    bgm_on = 0u;
    busy = 0u;
}

/* Clocked by the VBL interrupt, not by the main loop: the screen flip rewrites the whole BG
 * (tiles + map + attributes) and blocks its caller for ~6 frames (measured), which used to stop
 * the sequencer mid-note (S3).  VBlank also fires while the flip is running. */
static void snd_isr(void)
{
    snd_tick();
}

void snd_start(void)
{
    add_VBL(snd_isr);
}

void snd_play(uint8_t id)
{
    busy = 1u;
    eff_silence();
    eff_id = 0u;
    if (id == 0u || id > SND_NUM_EFFECTS) {
        busy = 0u;
        return;
    }
    eff_id = id;
    eff_pos = snd_eff_start[id];
    eff_load();
    busy = 0u;
}

void snd_bgm(uint8_t on)
{
    busy = 1u;
    if (on) {
        if (!bgm_on) {
            bgm_on = 1u;
            bgm_idx = 1u;
            bgm_f = 0u;
        }
    } else {
        bgm_on = 0u;
        NR22_REG = 0u;
        NR30_REG = 0u;
    }
    busy = 0u;
}

void snd_tick(void)
{
    if (busy)
        return;                /* the main loop is rewriting the state: catch up next frame */
    if (eff_id) {
        if (--eff_wait == 0u)
            eff_load();
    }
    if (!bgm_on)
        return;
    s_i = bgm_idx;
    if (bgm_f == 0u) {
        if (snd_bgm_t_hi[s_i] == SND_BGM_REST)
            NR30_REG = 0u;
        else {
            NR30_REG = 0x80u;
            NR32_REG = 0x20u;
            NR33_REG = gbc_bgm_w_lo[s_i];
            NR34_REG = (uint8_t)(0x80u | gbc_bgm_w_hi[s_i]);
        }
    }
    if (snd_bgm_p_hi[s_i] == SND_BGM_REST) {
        NR22_REG = 0u;
        bgm_vol = 0xFFu;
    } else {
        s_v = snd_bgm_env[bgm_f];
        if (bgm_f == 0u || s_v != bgm_vol) {
            bgm_vol = s_v;
            NR22_REG = (uint8_t)(s_v << 4);
            NR23_REG = gbc_bgm_p_lo[s_i];
            NR24_REG = (uint8_t)(0x80u | gbc_bgm_p_hi[s_i]);
        }
    }
    if (++bgm_f == SND_BGM_STEP) {
        bgm_f = 0u;
        if (++bgm_idx >= SND_BGM_LEN)
            bgm_idx = 1u;
    }
}
