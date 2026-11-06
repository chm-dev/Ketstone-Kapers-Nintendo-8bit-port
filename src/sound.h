#ifndef SOUND_H
#define SOUND_H
#include <stdint.h>

/* Sound effects (ids as docs/ATARI_RE_SPEC.md section 7; all share one voice, the newest wins). */
#define SND_NONE   0   /* snd_play(0) silences the current effect */
#define SND_BONUS  1   /* bonus tick: caller repeats it every 4 frames */
#define SND_WALK   2   /* walk step at pose 4 */
#define SND_JUMP   3   /* loops until snd_play(SND_NONE) on landing */
#define SND_PICKUP 4
#define SND_HIT    5
#define SND_DEATH  6

void snd_init(void);           /* once at boot: enable the APU channels, silence everything */
void snd_start(void);          /* once at boot, after snd_init(): tick the driver from the frame interrupt */
void snd_play(uint8_t id);     /* 1..6 start an effect, 0 stops the effect voice */
void snd_bgm(uint8_t on);      /* 1 = start the tune from its beginning (no-op if running), 0 = stop */
void snd_tick(void);           /* one frame of the sequencer; called by the frame interrupt (snd_start) */

#endif
