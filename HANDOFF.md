# HANDOFF (current status)

**Status 2026-11-05: NES game feature-complete (unplaytested by a human); GBC port in progress; DMG not started.**
Read `docs/DECISIONS_PENDING.md` FIRST: every unattended call/guess (E*, S*, SP*, G*, B*, H*, A*, C*) with how to revert.

## NES (`.\build.ps1` -> `roms/keystone_kapers.nes`)
Done: Kop/thief/timer engine (frame-exact vs 8 goldens), obstacles (matches obstacle goldens at the Python baseline of 17 torn rows), collisions/lives/score/bonus/pickups, title + game over, real sprites, cleaned backgrounds, HUD + minimap, escalator and elevator animation, APU sound.
Checks: `pwsh tests/run_models.ps1`, `pwsh tests/run_c_trace.ps1` (Mesen, ~21 s; `... obst` for obstacle chain).
Regeneration order after art changes: `gen_bg.py --emit` -> `gen_assets.py --emit` -> `gen_hud.py` -> `gen_dyn.py --emit` (build.ps1 refuses stale dyn data).
Not done / approximated: attract demo, long game-over countdown, music restart per life, true pixel collision (box-based), shared 4-palette quantisation artefacts (B2), pickup/hit sounds not captured (S2), Atari font (original 5x7 used), obstacle copy modes 4/6/7 untested, catch/death/radio/bonus only from disassembly (only ball hit has a capture).

## Playtest checklist (NES)
1. Title: SELECT cycles level 1-16, START begins; ~8 s intro music then Kop moves; time ticks ~every 2 s.
2. Walk all 8 screens both ways; Kop aligned to floors (X offset is `$30`); sprites correct facing; jump (A/B) and duck (down).
3. Escalators on screens 0/7 animate and carry Kop; elevator on screen 4: Up at doors, Kop vanishes while closed, reappears on new floor, Down exits.
4. Ball on screen 1 bounces; touching = 0.5 s freeze + hit sound, time drains, ball gone. Pickups +200/500/400/1000 by floor.
5. Higher levels (SELECT 4+): radios (jump >=6 px), carts, planes (duck), multiple copies.
6. Catch thief: +1000, bonus countdown with tick, next level. Time out: death, life lost, restart. Last life: GAME OVER, START restarts. Extra life per 10,000.
7. Thief reaching roof end on floor 3 kills Kop. HUD: score/level/hats/time, minimap markers for Kop/thief/car.
8. Sound: walk, 18-frame jump, hit, death, pickup, bonus; check by ear (all mappings are estimates, S1/S2).
9. Visual: black flash on screen change, margin overlap up to 7 px, palette artefacts, teal elevator colour.

## Next steps
- GBC port (agent in progress, `build_gbc.ps1`), then DMG (4-shade grey, no CGB palettes).
- Possible rework after the user's playtest: per-screen palettes (B2), attract demo, widen NES view beyond 160 px.
- Processes: stop `AltirraBridgeServer`, `MesenCE-MCP-Windows`, Gearboy at session end; build/*.lock must not linger.
- Do not read `docs/atari_disasm.txt` whole; grep by address.
