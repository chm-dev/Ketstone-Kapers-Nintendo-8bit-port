# MesenCE-MCP — operator notes

> **Scope note (Keystone Kapers port):** general tool knowledge copied from the River Raid / Robbo projects. Sections titled River-row / Robbo / Worked reference, and paths under `C:\dev\AI\robbo-port2`, are examples from those projects; use this workspace's paths (`./MesenCE-MCP`, `./gearboy`, `./gbdk`) and its own addresses.


Practical notes for an AI agent that must script **Mesen 2.2.1** through its built-in
MCP server. Paths are for this Windows machine.

## What is what

- **Mesen** — multi-system emulator (NES, SNES, Game Boy, GBA, PCE, SMS, WS).
  This build: `.\MesenCE-MCP\MesenCE-MCP-Windows.exe` in current workspace.
- **MesenCE-MCP** — the same GUI emulator with a **Streamable HTTP MCP server**
  built in. `--mcp` starts it; default endpoint
  `http://localhost:9100/mcp`.
- No SDK, no token file, and no authentication. It binds `localhost`; keep it
  that way. The wire format is JSON-RPC 2.0 over HTTP.
- The working client implementation is in `gb\tests\nes_*.mjs`
  (`nes_smoke.mjs` is the simplest). 57 tools are exposed in this build; use
  `tools/list` for the full schemas.
- Keep the whole `MesenCE-MCP` folder intact: the exe needs `MesenCore.dll`,
  `libSkiaSharp.dll` and `libHarfBuzzSharp.dll`.
- All command-line switches are listed in `MesenCE-MCP\commandline.md`.

## Start the server

The MCP server runs inside the GUI app, so a Mesen window will appear. Do not
wait for the process to exit; start it and keep the PID.
Paths are example from other project. Use ones from current workspace.
```powershell
$mesen = 'C:\dev\AI\robbo-port2\MesenCE-MCP\MesenCE-MCP-Windows.exe'
$logDir = Join-Path $env:TEMP 'mesen-mcp'
New-Item -ItemType Directory -Force $logDir | Out-Null
$stdout = Join-Path $logDir 'mesen.out'
$stderr = Join-Path $logDir 'mesen.err'
Remove-Item $stdout, $stderr -ErrorAction SilentlyContinue

$p = Start-Process $mesen -ArgumentList '--mcp','--mcp-port=9100','--enableStdout','--doNotSaveSettings','C:\dev\AI\robbo-port2\roms\robbo.nes' `
    -WorkingDirectory 'C:\dev\AI\robbo-port2' `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru

$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    if ($p.HasExited) { throw "Mesen exited early; see $stdout and $stderr" }
    if (Test-Path $stdout) { $ready = $ready -or (Select-String $stdout -Pattern 'MCP server started on port' -Quiet) }
    if (Test-Path $stderr) { $ready = $ready -or (Select-String $stderr -Pattern 'MCP server started on port' -Quiet) }
    if ($ready) { break }
    Start-Sleep -Milliseconds 250
}
if (-not $ready) { throw "Mesen MCP did not start; see $stdout and $stderr" }
"PID=$($p.Id)"
```

Observed log split:

- ROM loading and emulator output go to **stdout** (`Loading rom: ...`, header dump).
- .NET hosting/MCP startup lines go to **stderr**
  (`Now listening on: http://localhost:9100`, `MCP server started on port 9100`).
- Wait on **either** log, or just poll the port.

Useful flags:

- `--mcp` — enable the server; `--mcp-port=PORT` — custom port (default 9100).
- `--enableStdout` — mirror Mesen's log to stdout; useful for readiness/errors.
- `--doNotSaveSettings` — **use this** so command-line options do not become the
  user's persistent defaults in `settings.json`.
- Omit the ROM path to start with no game; then call `mesen_load_rom`.
- `--preferences.pauseWhenInBackground=false` and
  `--preferences.pauseWhenInMenusAndConfig=false` help when the GUI loses focus.
- `--video.videoFilter=None` and `--preferences.disableOsd=true` help for
  pixel-exact screenshots.
- `--nes.region=Ntsc` (or `Pal`, `Dendy`) forces the NES region; default is
  `Auto`.
- `--testRunner script.lua rom.nes` is a separate **headless Lua** path, not MCP.

Stop it with:

```powershell
Stop-Process -Id $p.Id -Force
# or, when you do not have the PID:
Stop-Process -Name MesenCE-MCP-Windows -Force
```

Only one process can listen on a given port. If startup fails, check for a stale
`MesenCE-MCP-Windows` process or reuse the existing server.

## MCP client bootstrap (Node)

Mesen uses the standard MCP Streamable HTTP handshake. The existing tests use
the following pattern; it is the reference implementation.

```js
const MCP_URL = process.env.MESEN_MCP_URL || 'http://localhost:9100/mcp';
let sessionId = null;
let nextId = 1;
const sleep = ms => new Promise(r => setTimeout(r, ms));

function parseSse(text) {
    const out = [];
    for (const block of text.split(/\r?\n\r?\n/)) {
        const data = block.split(/\r?\n/)
            .filter(line => line.startsWith('data:'))
            .map(line => line.slice(5).trimStart())
            .join('\n');
        if (data) out.push(JSON.parse(data));
    }
    return out;
}

async function post(body, useSession = true) {
    const headers = {
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream',
    };
    if (useSession && sessionId) headers['Mcp-Session-Id'] = sessionId;
    const res = await fetch(MCP_URL, { method: 'POST', headers, body: JSON.stringify(body) });
    const text = await res.text();
    const sid = res.headers.get('mcp-session-id');
    if (sid) sessionId = sid;
    if (!res.ok) throw new Error(`MCP HTTP ${res.status}: ${text}`);
    return parseSse(text);
}

async function init() {
    await post({
        jsonrpc: '2.0', id: nextId++, method: 'initialize',
        params: {
            protocolVersion: '2024-11-05',
            capabilities: {},
            clientInfo: { name: 'agent', version: '1.0' },
        },
    }, false);
    await post({ jsonrpc: '2.0', method: 'notifications/initialized', params: {} });
}

async function callTool(name, args = {}) {
    const messages = await post({
        jsonrpc: '2.0', id: nextId++, method: 'tools/call',
        params: { name, arguments: args },
    });
    const msg = messages.find(m => m && m.result);
    if (!msg) {
        const err = messages.find(m => m && m.error);
        throw new Error(`${name}: ${err ? err.error.message : 'no result'}`);
    }
    if (msg.result.isError) {
        const detail = (msg.result.content || [])
            .filter(c => c.type === 'text')
            .map(c => c.text)
            .join('\n');
        throw new Error(`${name}: ${detail || 'tool error'}`);
    }
    return msg.result.content
        ?.filter(c => c.type === 'text')
        .map(c => c.text)
        .join('\n') ?? '';
}

async function readBytes(addr, length, memoryType = 'NesMemory') {
    const text = await callTool('mesen_read_memory', {
        address: `0x${addr.toString(16)}`,
        length,
        memoryType,
    });
    return text.trim().split(/\s+/).filter(Boolean).map(h => parseInt(h, 16));
}
```

Handshake rules:

- `initialize` must be the first request; send it **without** `Mcp-Session-Id`.
- Capture the `Mcp-Session-Id` response header and send it on every later request.
- Send `notifications/initialized` (no `id`) after `initialize`.
- Always send `Accept: application/json, text/event-stream`; the server replies
  with SSE.
- A response can contain several SSE messages; find the one with `result` or
  `error`. Tool results are in `result.content`, usually a text block.
- Non-2xx HTTP responses contain a useful error body; surface it.

## Minimal NES session

```js
await init();

console.log(await callTool('mesen_get_status'));
console.log(await callTool('mesen_list_cpu_types'));    // -> Nes
console.log(await callTool('mesen_list_memory_types')); // -> NesMemory etc.

// If the ROM was not given on the command line:
await callTool('mesen_load_rom', { filepath: 'C:\\dev\\AI\\robbo-port2\\roms\\robbo.nes' });
await sleep(900);

// Clear the battery-backed save record, then power-cycle.
await callTool('mesen_write_memory', {
    address: '0x7FF0',
    hexData: '00000000000000000000000000000000',
    memoryType: 'NesMemory',
});
await callTool('mesen_reset', { type: 'hard' });
await sleep(1200);

// Press START for 220 ms.
await callTool('mesen_input_override', { action: 'set', port: 0, buttons: 'Start' });
await sleep(220);
await callTool('mesen_input_override', { action: 'set', port: 0, buttons: '' });
await sleep(1500);

console.log(await readBytes(0x6000, 16));

await callTool('mesen_take_screenshot', {
    outputFile: 'C:\\Users\\<user>\\AppData\\Local\\Temp\\mesen-shot.png',
});
```

## Tool catalog

The server exposes 57 tools. The frequently used ones:

| Task | Tool and key arguments |
|---|---|
| Status / lifecycle | `mesen_get_status`; `mesen_playback {action:"pause" / "resume"}`; `mesen_load_rom {filepath:"C:\\abs\\game.nes"}`; `mesen_reset {type:"soft" / "hard"}` |
| Discovery | `mesen_list_cpu_types`; `mesen_list_memory_types` — call these before any `cpuType` / `memoryType` parameter |
| Save states | `mesen_save_state {action:"save" / "load", slotOrPath:"1".."10" or "C:\\abs\\state"}` |
| Stepping | `mesen_step {cpuType:"Nes", count:1, stepType:"PpuFrame" / "PpuScanline" / "PpuStep" / "CpuCycleStep" / "Step" / "StepOver" / "StepOut"}`; `mesen_resume_execution` |
| Memory read | `mesen_read_memory {address:"0x6000", length:16, memoryType:"NesMemory", outputFile?}` — max 4096 bytes |
| Memory write | `mesen_write_memory {address:"0x7FF0", hexData:"0000...", memoryType:"NesMemory"}` |
| Memory search / info | `mesen_search_memory {patternHex:"AD0020", memoryType:"NesMemory", startAddress?, endAddress?, maxResults?}`; `mesen_get_address_info`; `mesen_memory_access_counts` |
| CPU state | `mesen_get_state {component:"cpu", cpuType:"Nes"}` — text |
| PPU state | `mesen_get_state {component:"ppu", cpuType:"Nes"}` — JSON string |
| ROM info | `mesen_get_rom_info`; `mesen_get_rom_header` (NES/SNES) - the latter returns a JSON string |
| Input | `mesen_input_override {action:"set", port:0, buttons:"Start,Select"}`; clear with `buttons:""` |
| Screenshot | `mesen_take_screenshot {outputFile:"C:\\abs\\shot.png"}` — also returns an image content block |
| Lua | `mesen_run_lua_script {code:"...", waitMs:200, persistent:false}`; `mesen_remove_lua_script {scriptId:N}` |
| Breakpoints | `mesen_breakpoint {action:"set" / "remove" / "remove_all" / "list", address, type:"Execute,Read,Write", memoryType, cpuType, condition?}` |
| Disassembly | `mesen_disassemble {address:"0xC000", lineCount:8, cpuType:"Nes"}`; `mesen_assemble {code, startAddress, cpuType}`; `mesen_find_occurrences {searchString, cpuType}` |
| Expressions | `mesen_evaluate_expression {expression:"PC", cpuType:"Nes"}` |
| Call stack | `mesen_get_callstack {cpuType:"Nes"}` |
| Trace | `mesen_set_trace_options`; `mesen_get_execution_trace {count, cpuType?}`; `mesen_clear_execution_trace`; `mesen_trace_file {action:"start" / "stop", filepath}` |
| Profiler | `mesen_profiler {action:"get" / "reset", cpuType:"Nes", outputFile?}` |
| PPU inspection | `mesen_get_palette`; `mesen_set_palette_color`; `mesen_get_sprite_list`; `mesen_get_tilemap_info`; `mesen_get_tilemap_tile_info`; `mesen_get_tile_pixel`; `mesen_set_tile_pixel` |
| CDL / text / labels | `mesen_mark_bytes_as`; `mesen_get_cdl_statistics`; `mesen_get_cdl_functions`; `mesen_cdl_file`; `mesen_load_tbl`; `mesen_get_tbl_info`; `mesen_search_text`; `mesen_decode_text`; `mesen_relative_search`; `mesen_label` |
| Cheats / patches | `mesen_set_cheats`; `mesen_clear_cheats`; `mesen_freeze_address`; `mesen_save_modified_rom` |
| History | `mesen_history_state`; `mesen_history_navigate`; `mesen_history_export` — requires rewind/history |

Addresses accept decimal, `0x...`, or `$...` strings. Tool results are usually
plain text, but `mesen_get_rom_header` and `mesen_get_state {component:"ppu"}`
return **JSON strings** that must be parsed.

## Timing and stepping

- There is **no “run N frames” tool**. Mesen runs in real time while MCP calls
  are served; the existing tests pace with `sleep(ms)`.
- `mesen_get_status` returns a line like
  `Running Nes robbo 60.1fps frame=2461`. The `frame=` counter is the best
  pacing signal.
- `mesen_playback {action:"pause"}` freezes the frame counter; `resume` restarts
  it. In 2.2.1, `mesen_get_status` can still say `Running` while paused — confirm
  pause by observing that `frame=` does not change.
- `mesen_step {stepType:"PpuFrame"}` advances exactly one frame while paused
  (verified). Use it when you need deterministic frames; use `sleep()` for
  gameplay tests, which is the proven pattern.
- The MCP round-trip is roughly 100 ms. Poll with `sleep(100..200)` rather than a
  tight loop; the tests use helper loops with 100–200 ms waits.
- After `mesen_load_rom` or `mesen_reset`, wait for the frame counter to move
  (roughly 0.7–1.8 s in the tests) before issuing save-state, breakpoint or
  debugger calls. Doing so during the reset window can block.
- `mesen_load_rom` returns `Loaded: <name> (<format>, <system>)`; `mesen_reset`
  returns `Reset (soft)` or `Reset (hard)`. `soft` is the reset button and
  preserves RAM; `hard` power-cycles and clears work RAM.

## Input

`mesen_input_override` **latches** the override until you clear it:

```js
await callTool('mesen_input_override', { action: 'set', port: 0, buttons: 'Start' });
await sleep(220);
await callTool('mesen_input_override', { action: 'set', port: 0, buttons: '' });
```

- NES ports: `0` (the only port reported for the Robbo ROM).
- Buttons: `A,B,X,Y,L,R,Up,Down,Left,Right,Select,Start`; comma-separated.
- Always clear in a `finally` block; a stuck override is the usual cause of
  “the game keeps moving by itself”.
- `mesen_input_override {action:"list"}` reports available ports.

## Memory and NES types

Call `mesen_list_memory_types` first; names and sizes vary by system and mapper.
For the Robbo NES ROM this build reports:

| Memory type | Size | Notes |
|---|---:|---|
| `NesMemory` | 65536 | CPU address space; use for `$6000-$7FFF` PRG-RAM and normal RAM |
| `NesPpuMemory` | 16384 | PPU address space |
| `NesPrgRom` | 524288 | PRG ROM image (size follows the ROM) |
| `NesInternalRam` | 2048 | 2 KiB work RAM |
| `NesSaveRam` | 8192 | Battery-backed save RAM |
| `NesNametableRam` | 2048 | Nametables |
| `NesSpriteRam` | 256 | OAM |
| `NesSecondarySpriteRam` | 32 | Secondary OAM |
| `NesPaletteRam` | 32 | Palette |
| `NesChrRam` | 8192 | CHR RAM |

Memory notes:

- `mesen_read_memory` returns a hex text string (`25 00 30 ...`); parse it into
  bytes. Max length is 4096; use `outputFile` for a larger raw dump.
- `mesen_write_memory` takes contiguous hex (`hexData:"EAEA"`), no `0x` prefix.
- `NesMemory` covers the CPU address space; PRG-RAM at `$6000-$7FFF` is readable
  and writable there.
- A **hard reset** clears work RAM but battery-backed save RAM can persist.
  Clear the save record explicitly when a test needs a clean slate.
- `mesen_search_memory` searches hex patterns over the CPU view and caps the
  range at 1 MB; `maxResults` defaults to 50.

### This project: playfield reconstruction

- Vertical mirroring means NT0 is `NesNametableRam[0x000..0x3FF]` and NT1
  (the river) is `NesNametableRam[0x400..0x7FF]`.
- BG CHR is at `NesPpuMemory[0x0000..0x0FFF]` on this build.  `set_bkg_data`
  de-interleaves GBDK's row-interleaved source into NES planar CHR.
- Reconstruct the playfield with
  `python tools/inspect_playfield.py <playfield_scroll_y>`: it reads
  `build/nt1.bin`, `build/chr.bin` and `build/flip_check.png`.  With the
  current split handler the playfield's top nametable coordinate is
  `playfield_scroll_y`; before the fix it was `playfield_scroll_y + 36`.
- **GBDK split quirk:** the deferred LCD ISR adds the current scanline to
  `bkg_scroll_y` when it writes the entry.  The LCD handler must subtract
  `HUD_SPLIT_SCANLINE` (mod 240) before `move_bkg()`, or the playfield is
  36 px ahead of the ring and the newest row appears at the bottom.
- **Test attachment quirk:** writing `river_freeze`/`playfield_scroll_y`
  while paused can be overwritten by an in-flight `river_update` when the
  CPU resumes.  Resume for ~100 ms, pause, then re-assert the value before
  taking the screenshot.
- Suites: `node tests/nes_smoke.mjs` (HUD/CHR/RAM), `node
  tests/nes_scroll_hud.mjs` (split, 1-px shift, HUD), `node
  tests/nes_river.mjs` (rows/state/collision).  All three pass.

## Results and screenshots

- `mesen_take_screenshot` captures the current frame. With `outputFile` it writes
  the PNG on the server side and returns a `Saved to ...` text block plus a
  base64 `image` block. Without `outputFile`, only the image block is returned.
- NES screenshots are **256x240** PNGs in this build.
- A screenshot taken while the emulator is running can capture a partially
  rendered frame. For pixel-exact assertions, pause, call
  `mesen_step {cpuType:"Nes", count:1, stepType:"PpuFrame"}`, then take the
  screenshot. Freeze any game-controlled scroll first so the step does not
  advance it.
- Use absolute paths for `outputFile`, `mesen_save_state` file paths, and
  `mesen_load_rom` paths.
- `mesen_get_state {component:"cpu"}` returns text such as
  `Nes PC=$C36D A=$97 X=$EF Y=$00 SP=$F4 PC=$C369 PS=$07 flags=nv-bdIZC`.
  Parse it with a regex; it is not JSON.
- `mesen_get_state {component:"ppu"}` returns a JSON string with `scanline`,
  `cycle`, `frameCount`, `verticalBlank`, `sprite0Hit`, `spriteOverflow`,
  `videoRamAddr` and `scrollX`.
- `mesen_get_rom_header` returns a JSON string with `format`, `mapper`,
  `prgRomSize`, `chrRomSize`, `mirroring`, `battery`, `trainer`.
- `mesen_get_rom_info` returns a one-line text summary including the SHA-1.

## Lua scripting

> Profiling recipe (used for the river frame-time work): Lua `io`/`os` are disabled, and a non-persistent script is removed after `waitMs`, so use `persistent:true` and report results through spare NES RAM (`emu.write`), read back with `mesen_read_memory`. Exec callbacks (`emu.addMemoryCallback(cb, emu.callbackType.exec, addr)`) plus `emu.getState()["cpu.cycleCount"]` give per-function cycle counts; a range callback over `$8000-$FFFF` works but slows emulation ~100x, so profile ~60 frames at a time.

> Lessons from the river performance work (`tests/perf_*.mjs` are working examples):
> - A per-instruction exec callback (`emu.addMemoryCallback(cb, emu.callbackType.exec, 0x8000, 0xFFFF)`) is fine **while paused and frame-stepping** (`mesen_step ... PpuFrame`; 300 frames take a minute or two); the ~100x slowdown only matters at real-time speed. In the callback the second argument is the opcode, so a 256-entry cycle table gives per-function cycle estimates without `emu.getState()` (which is slow per call).
> - Publish results with `emu.write(0x1F00 + i, v, emu.memType.nesChrRam)` from an `emu.eventType.endFrame` callback and read them back with `mesen_read_memory memoryType:'NesChrRam'`; check which CHR tiles the game really uses before picking a mailbox.
> - **Persistent scripts survive `mesen_load_rom`** (and keep writing to the mailbox): restart the Mesen process between profiling runs; do not rely on `mesen_remove_lua_script`.
> - Read symbol addresses from the `.noi` on every run; they move whenever the RAM layout changes. Static variables of fixed-bank files have symbols, statics of banked files and static functions of banked files do not.
> - `mesen_load_rom` needs an absolute path; `mesen_take_screenshot {outputFile}` writes a PNG you can open.
> - To compare two ROMs, load each in turn, run the same input script frame by frame, and diff what you read (OAM, tile pixels): `tests/compare_oam.mjs`, `tests/compare_tile_rows.mjs`.

`mesen_run_lua_script` runs a script inside Mesen and returns its log output.
Use **`emu.log(...)`**, not Lua `print`: `print` output was not returned by the
MCP call in probing, while `emu.log` lines were.

```lua
local s = emu.getState()
emu.log('frame=' .. tostring(s['frameCount']))
emu.log('p1=' .. tostring(s['apu.square1.envelope.volume']))
```

- `emu.read(addr, emu.memType.nesMemory)` and
  `emu.write(addr, value, emu.memType.nesMemory)`.
- `emu.getState()` returns dotted Mesen state keys such as
  `apu.square1.envelope.volume`, `apu.square1.duty`, `frameCount`.
- Per-frame callbacks:
  `emu.addEventCallback(fn, emu.eventType.endFrame)`.
- `waitMs` defaults to 200 and is capped at 5000.
- `persistent:true` keeps the script running and returns `Script #N running
  (persistent).`; remove it with `mesen_remove_lua_script {scriptId:N}`. The
  regression tests call removal in cleanup and ignore failures, so do not make
  correctness depend on removal.
- For bulk data, write results to RAM (`emu.write`) and read them back with
  `mesen_read_memory`; that is how the APU sampler in `nes_phase5.mjs` works.

## Debugger and breakpoints

- `mesen_breakpoint {action:"set", address:"0xC000", type:"Execute",
  memoryType:"NesMemory", cpuType:"Nes", condition?}` works; `list` shows the
  active breakpoints and `remove_all` clears them.
- After a breakpoint stop, `mesen_get_state {component:"cpu"}` reports the PC;
  `mesen_resume_execution` continues.
- `mesen_evaluate_expression {expression:"PC", cpuType:"Nes"}` works and returns
  e.g. `50025 ($C369)`.
- `mesen_disassemble` is present, but in 2.2.1 probing it returned the debugger's
  current view rather than the requested address. Check the first returned
  address before relying on it for arbitrary ranges.
- `mesen_step` is the reliable single-instruction/frame advance.
- Save states are synchronous once the emulator has settled: `Saved slot 1`,
  `Loaded slot 1`. Slots are `1`–`10`; an absolute path is also accepted.

## Worked reference: Robbo NES

- ROMs: `roms\robbo.nes` (release), `roms\robbo-debug.nes` (debug hooks).
- Symbol files: `roms\robbo-nes.noi`, `roms\robbo-debug-nes.noi`. The tests parse
  lines matching `^DEF (\S+) (0x[0-9A-Fa-f]+)$`.
- Canonical client: `gb\tests\nes_smoke.mjs`. It loads the ROM, waits 700 ms,
  clears `$7FF0`, hard-resets, waits 1200 ms, presses START through
  `mesen_input_override`, and reads the map through `NesMemory`.
- Other references: `nes_title.mjs` (title/save menu), `nes_phase2.mjs`
  (HUD/ring scrolling), `nes_phase3.mjs` (palette/attributes), `nes_phase5.mjs`
  (APU, persistent Lua sampler), `nes_door.mjs` (input/APU/door).
- Run them with the server already up:
  `node gb\tests\nes_smoke.mjs` (or set `MESEN_MCP_URL` for a non-default port).
  The tests call `mesen_load_rom` themselves, but a stale server on the same port
  can still serve the wrong session; restart if in doubt.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `fetch failed` / connection refused | Server not up, wrong port, or process exited. Check `mesen.out` / `mesen.err`; confirm `MCP server started on port`. |
| HTTP 4xx | Missing `Accept: application/json, text/event-stream`, or missing `Mcp-Session-Id` after initialize. |
| `initialize` rejected | Use protocol version `2024-11-05`; send `notifications/initialized` before tools. |
| Tool returns no result | Parse SSE blocks and find `result`; also check for an `error` object. |
| `Invalid memory type` | Call `mesen_list_memory_types` first; names are case-sensitive. |
| Read is truncated | `mesen_read_memory` max is 4096 bytes; use `outputFile` for larger dumps. |
| Input stuck | Clear the override with `buttons:""`; do it in `finally`. |
| Emulation not advancing | It may be paused: `mesen_playback {action:"resume"}`; check `frame=` in `mesen_get_status`. |
| Save-state call hangs | Wait until load/reset has settled (frame counter moving), then retry; do not save during the reset window. |
| Screenshot missing | Use an absolute `outputFile`; the path is on the server side. |
| Lua output missing | Use `emu.log(...)`, not `print(...)`; `waitMs` must be long enough. |
| GUI dialog blocks tools | A modal Mesen dialog can stall requests; close it or restart the process. |
| Port already in use | Reuse the running server or start another on a different `--mcp-port`. |

## Cleanup

- Remove breakpoints: `mesen_breakpoint {action:"remove_all"}`.
- Resume after a stop: `mesen_resume_execution`.
- Remove persistent Lua scripts:
  `mesen_remove_lua_script {scriptId:N}` (ignore cleanup failures).
- Stop the process:

```powershell
Stop-Process -Id <server-pid> -Force
# or
Stop-Process -Name MesenCE-MCP-Windows -Force
```

Remove temporary screenshots/logs when finished. Do not commit ROM save data or
temporary state files.

## Reference files

- `C:\dev\AI\robbo-port2\MesenCE-MCP\commandline.md` — every emulator flag.
- `C:\dev\AI\robbo-port2\gb\tests\nes_smoke.mjs` — minimal working MCP client.
- `C:\dev\AI\robbo-port2\gb\tests\nes_title.mjs`, `nes_phase2.mjs`,
  `nes_phase3.mjs`, `nes_phase5.mjs`, `nes_door.mjs` — richer examples.
- `C:\dev\AI\robbo-port2\AGENTS.md` — Mesen/MCP section and NES port context.
- `tools/list` from the running server — authoritative tool names and schemas.
