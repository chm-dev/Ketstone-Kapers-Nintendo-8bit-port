# Decisions & unknowns needing the user's review

Unattended orchestration session started 2026-11-04. Every call made without the user, every guess where the RE is incomplete, and every workaround goes here. Format per entry:

**ID - title** | decision | why | touched files/symbols | how to revert / rework

Agents: APPEND ONLY (add at the bottom, keep entries short). Do not ask the user; pick a reversible default and log it.

---

**D1 - Git commits allowed this session** | The user said "do not push, just commit"; this overrides the AGENTS.md "no git commits" rule for this session only. Only the orchestrator commits (after verified milestones); agents never run git write commands. Never push. | user instruction | - | Squash/reset local commits as wished.

**D2 - Golden-trace diff replaces human playtests** | With no human in the loop, "done" for engine steps = build passes + C traces match `tests/golden/*.txt` (frame-exact) in Mesen. Gameplay feel is NOT human-verified; a playtest checklist is in HANDOFF.md for when the user returns. | no human available | tests/ | Playtest and report differences.

**D3 - Emulator single-owner locks** | Altirra and Mesen servers use fixed ports; agents serialize with lock dirs `build/altirra.lock` and `build/mesen.lock` (create with `New-Item -ItemType Directory`; fails if held; remove when done; always stop the server on exit). | avoid port collisions | build/ | - |
