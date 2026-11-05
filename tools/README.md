# Tools (run from the repo root; Python via `python -I`)

| Tool | Purpose |
|---|---|
| `dump_xex.py` | Split the XEX into segments (`assets/atari/segments/`, gitignored). |
| `dis6502.py` | Linear 6502 disassembler for a file at a base address. |
| `rdis.py` | Recursive-descent disassembler of `assets/atari/keystone_image_9f80_bfff.bin` -> `docs/atari_disasm.txt`. Uses `tools/symbols.txt` and `assets/atari/runtime/coverage.txt`. |
| `atari_coverage.py` | Boot in Altirra, scripted play under the profiler, writes executed PCs. |
| `atari_snapshot.py` | Deterministic boot + input timeline, screenshot, RAM dump, hw state (`--start`, `--hold`, `--fire`). |
| `altirra_probe.py` | General AltirraBridge CLI (copied from river-raid; check its addresses before use). |
| `render_dl.py` | Decode the display list of a RAM dump and render mode-C rows (WIP: does not yet match the screenshot). |
| `gen_proof.py` | Milestone-0 asset: dedupes live bitmap rows into NES tiles -> `src/proof_data.*`. |
| `patch_nes_header.py` | Forces iNES vertical mirroring (called by `build.ps1`). |
| `atari_trace.py` | Per-frame RAM columns under an input plan (`dir[+fire]:frames`; text after `+` = fire!). `--poke ADDR=VAL` teleports/sets state after the settle. |
| `atari_events.py` | Change-log of RAM bytes under a plan (`--ranges`, `--ignore`, `--poke`, `--shots`). |
| `atari_sound.py` | POKEY register changes per frame + sound ids (`--poke`, `--from-boot`). |
| `atari_lives.py` | Forces time-outs to log lives / game-over flow. |
| `atari_screens.py` | Walks all 8 screens, builds per-pixel-mode background composites. |
| `atari_ramdiff.py` | Diff `$00-$1FF` per input over time (first mapping pass). |
| `dl_dump.py` | Decode a display list from a RAM dump. |
| `kk_model.py` | Reference model (Kop, Thief); tests in `tests/` (`tests/run_models.ps1`). |
| `extract_data.py` | ROM tables + measured sequences -> `assets/data/keystone_data.json`. |
| `atari_sprite_probe.py` | Live sprite/PMG captures for sprite RE. |
| `gen_assets.py` | Sprite export -> `src/spr_data.c/.h` (`--emit`, `--verify`). |
| `obstacle_model.py` | Obstacle reference model, replays `tests/golden/obst_*.txt` (baseline 17 torn mismatches). |
| `gen_hud.py` | HUD font / hat / margin tiles + minimap marker sprites -> `src/hud_data.c/.h` (PRG bank 1). Reads the palettes in `src/bg_data.c` / `spr_data.c` to pick colours: re-run after `gen_bg.py --emit` / `gen_assets.py --emit`. |
