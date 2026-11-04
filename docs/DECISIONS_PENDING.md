# Decisions & unknowns needing the user's review

Unattended orchestration session started 2026-11-04. Every call made without the user, every guess where the RE is incomplete, and every workaround goes here. Format per entry:

**ID - title** | decision | why | touched files/symbols | how to revert / rework

Agents: APPEND ONLY (add at the bottom, keep entries short). Do not ask the user; pick a reversible default and log it.

---

**D1 - Git commits allowed this session** | The user said "do not push, just commit"; this overrides the AGENTS.md "no git commits" rule for this session only. Only the orchestrator commits (after verified milestones); agents never run git write commands. Never push. | user instruction | - | Squash/reset local commits as wished.

**D2 - Golden-trace diff replaces human playtests** | With no human in the loop, "done" for engine steps = build passes + C traces match `tests/golden/*.txt` (frame-exact) in Mesen. Gameplay feel is NOT human-verified; a playtest checklist is in HANDOFF.md for when the user returns. | no human available | tests/ | Playtest and report differences.

**D3 - Emulator single-owner locks** | Altirra and Mesen servers use fixed ports; agents serialize with lock dirs `build/altirra.lock` and `build/mesen.lock` (create with `New-Item -ItemType Directory`; fails if held; remove when done; always stop the server on exit). | avoid port collisions | build/ | - |

**S1 - Sound: POKEY -> NES APU mapping** | Effects use ONE voice (newest wins, like POKEY ch1): pure tone (AUDC dist 5) -> pulse 1 50%, poly4 (C/E) -> pulse 1 25%, poly5/poly17 -> noise (poly5 = periodic mode), noise period = nearest NES index to 63921/(AUDF+1) Hz; pulse timer = 3.5*(AUDF+1)-1. BGM: POKEY ch3 -> pulse 2 (50%), ch4 -> triangle (same timer pitch formula 1.75*(N+1)-1, so same pitch as the tone; fixed loudness, no envelope), AUDF 0 = rest. Volumes copied 1:1 (POKEY 0..15 -> APU 0..15); BGM envelope 9,9,9,9,9,8,6,4,2,0 per 10-frame step from timeout.txt 70..79. The first 69 frames of that capture show BGM vol 2/1/0 instead (timeout state, not modelled). | no ear-check possible unattended | src/sound*.c/h, tools/gen_sound.py | retune the formulas in tools/gen_sound.py (convert_step, pulse_timer) and re-run it.

**S2 - Sound effects 4 (pickup) and 5 (hit) are not captured** | Built from spec text only: pickup AUDF 06 05 03 02 01 x 4 frames, vol 8..4 (20 frames); hit AUDF $18, vol 8..0 x 4 frames (36 frames). Effects 1,2,3,6 are cut frame-exact from the captures (jump loops `CF,4F,4F,4F`, so the engine must call snd_play(0) on landing; bonus tick is 1 frame, caller repeats every 4 frames; walk is 2 frames). | spec 7 gives only the shape | build_effects() in tools/gen_sound.py | capture id 4/5 with tools/atari_sound.py and cut like the others.
