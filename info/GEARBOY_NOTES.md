# Gearboy (GB/GBC emulator with MCP server)

`./gearboy/Gearboy.exe`, gitignored, local to this machine.
- Launch headless: `gearboy/Gearboy.exe --headless --mcp-http --mcp-http-port 7777 rom.gb rom.noi`. Endpoint `http://127.0.0.1:7777/mcp`.
- Starts paused: call `debug_continue`.
- Requests after `initialize` need header `MCP-Protocol-Version: 2025-11-25`.
- Memory: `read_memory` area 6 = WRAM, offsets from `$C000`.
- Profiler: units of 70,224 per frame at any CPU speed; M-cycles = units/4 (single speed) or units/2 (double speed).
- Fast-forward does not speed up headless runs; keep benchmarks short.
- Stop the process when finished.
- Working clients/recipes live in the river-raid project: `tests/gb/gearboy_client.mjs`, `tests/gb/profile_play.mjs`, `tests/gb/run_emu.ps1`, `tests/gb/sprite_check.mjs`. Copy them when the GB phase starts.
