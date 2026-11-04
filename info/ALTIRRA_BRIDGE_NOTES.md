# Altirra / AltirraBridge — operator notes

> **Scope note (Keystone Kapers port):** general tool knowledge copied from the River Raid / Robbo projects. Sections titled River-row / Robbo / Worked reference, and paths under `C:\dev\AI\robbo-port2`, are examples from those projects; use this workspace's paths (`./MesenCE-MCP`, `./gearboy`, `./gbdk`) and its own addresses.


Practical notes for an AI agent that must script the Atari 8-bit emulator. Paths are
for this Windows machine; the SDK itself is cross-platform.

## What is what

- **Altirra** — cycle-accurate Atari 800 / 800XL / 5200 emulator. GUI here:
  `F:\Emu\Atari800\Altirra\Altirra64.exe` (v4.40; manual: `Altirra.chm`).
- **AltirraBridge** — scripting layer over Altirra's core, JSON over TCP.
  - `F:\Emu\Atari800\Altirra\AlitrraBridge\AltirraBridgeServer.exe` — headless,
    lean build, no window/audio. **Use this for automation.**
  - `AltirraSDL --bridge` — GUI build with the same bridge (not installed here).
- Python SDK: `F:\Emu\Atari800\Altirra\AlitrraBridge\sdk\python`
  (`altirra_bridge`, pure stdlib, Python >= 3.9).
- Package here: commit `288e2b03`, built 2026-10-26, Windows x86_64. The Windows
  binary needs the VC++ 2015-2022 redistributable (normally already present).
- Note the folder spelling: **`AlitrraBridge`** (not "Altirra").

## Start the server

Generic form: `AltirraBridgeServer --bridge=tcp:127.0.0.1:6502`. On Unix-like
systems the token/log files land in `/tmp`; on Windows they land in `%TEMP%`.

```powershell
$bridge = 'F:\Emu\Atari800\Altirra\AlitrraBridge\AltirraBridgeServer.exe'
$logDir = Join-Path $env:TEMP 'altirra-agent'
New-Item -ItemType Directory -Force $logDir | Out-Null
$stderr = Join-Path $logDir 'bridge.err'
$stdout = Join-Path $logDir 'bridge.out'
Remove-Item $stderr, $stdout -ErrorAction SilentlyContinue

$p = Start-Process $bridge -ArgumentList '--bridge=tcp:127.0.0.1:6502' `
    -RedirectStandardError $stderr -RedirectStandardOutput $stdout -PassThru

# Wait for the token path printed on stderr.
for ($i = 0; $i -lt 100; $i++) {
    if ((Test-Path $stderr) -and (Select-String $stderr -Pattern 'token-file:' -Quiet)) { break }
    Start-Sleep -Milliseconds 100
}
if (-not (Test-Path $stderr) -or -not (Select-String $stderr -Pattern 'token-file:' -Quiet)) {
    throw "AltirraBridgeServer did not start; see $stderr"
}
$token = (Select-String $stderr -Pattern 'token-file:\s*(.+)$').Matches[0].Groups[1].Value.Trim()
"PID=$($p.Id) TOKEN=$token"
```

- `--bridge=tcp:127.0.0.1:0` lets the OS pick a port; a fixed port is easier.
  If a server is already listening on the chosen port, reuse its token instead of
  starting another one.
- `--pacing=realtime` makes headless frames run at real PAL/NTSC speed; default is
  as fast as the host CPU allows.
- `--mcp[=7750]` additionally serves MCP at `http://127.0.0.1:7750/mcp`.
- `--settings=user` inherits the user profile; default is isolated deterministic
  settings (do not use it unless the task requires the user's setup).

The server prints:

```text
[Bridge] listening on tcp:127.0.0.1:6502
[Bridge] token-file: C:\Users\<user>\AppData\Local\Temp/altirra-bridge-<pid>.token
[Bridge] log-file:  C:\Users\<user>\AppData\Local\Temp/altirra-bridge-<pid>.log
```

- Token file line 1 = bound address, line 2 = 128-bit session token.
- `AltirraBridge.from_token_file(path)` does connect + HELLO.
- The raw token is also printed on stderr (`[Bridge] token: ...`), but
  `from_token_file` is preferred. Manual fallback:
  `a = AltirraBridge(); a.connect("tcp:127.0.0.1:6502"); a.hello(TOKEN)`.
- The token changes on every server restart; never cache it. The token file is
  deleted on clean shutdown, so a stale path means that server is gone.
- If you did not capture stderr, find the newest token with:
  `Get-ChildItem $env:TEMP\altirra-bridge-*.token | Sort-Object LastWriteTime | Select-Object -Last 1`
- The `.log` file is the first thing to inspect when state is wrong.
- `a.quit()` asks the server to exit. `a.close()` only closes the socket.

Observed server defaults: `machine=800XL`, `memory=320K`, `video=pal`,
BASIC off, fast boot on, SIO patch on, `artifact=none`, addons off.

## Minimal Python session

```python
import sys
sys.path.insert(0, r"F:\Emu\Atari800\Altirra\AlitrraBridge\sdk\python")
from altirra_bridge import AltirraBridge

TOKEN = r"C:\Users\<user>\AppData\Local\Temp\altirra-bridge-<pid>.token"

with AltirraBridge.from_token_file(TOKEN) as a:
    print(a.ping())
    print(a.config())

    a.boot(r"C:\path\to\game.xex")   # only arms the loader
    a.frame(300)                     # next command blocks until 300 frames pass
    print(a.regs())
    open("shot.png", "wb").write(a.screenshot())

    a.quit()
```

`boot()` returns when the emulator accepted the image, **not** when the program
has loaded or RUNAD has run. Always `frame(240)`–`frame(300)` (or more) before
reading state; many PAL XEX files need >120 frames.

## Core semantics

- **`frame(n)` is a gate, not a sleep.** It returns immediately; the *next*
  command waits server-side until n frames have been emulated. Sleeping in
  Python does not advance a paused emulator.
- Headless frame steps are decoupled from wall-clock time. Use
  `--pacing=realtime` when real-time behaviour matters.
- `pause()` / `resume()` control free-running emulation; `pause()` also cancels
  an active frame gate. `cycles(n)` and `scanlines(n)` (114 machine cycles each)
  are sub-frame steps; `clock()` is the completion barrier and reports
  `step_completed`.
- `boot()` / `mount()` are asynchronous on `AltirraSDL --bridge`, synchronous
  on `AltirraBridgeServer`. On both, wait frames for the guest to initialise.
- Save-state commands are synchronous. `state_load` preserves pause state: a
  paused machine stays paused; call `resume()` to continue. `cold_reset()` and
  `warm_reset()` also preserve pause state.
- `peek()` / `memdump()` are debug-safe: reading `$D000-$D7FF` does not trigger
  chip side effects. `poke()` is a real CPU bus write and **does** trigger them
  (e.g. `PORTB` banking). `hwpoke()` writes a hardware register in the current
  bank; use it when that is what you mean.
- Input is owned by the bridge; disconnect cleanup releases keys, joystick
  directions and console switches. The bridge is single-client and not
  thread-safe; do not share one connection across threads.
- `checkpoint()` is the workhorse for experiments: save, mutate/measure, and
  auto-rewind on block exit.

## API cheat sheet

All calls raise `RemoteError` on a rejected command, `AuthError` on a bad token,
and `BridgeError` for transport/protocol failures.

| Goal | Python call |
|---|---|
| Health / lifecycle | `a.ping()`, `a.pause()`, `a.resume()`, `a.warp(True)`, `a.quit()` |
| Step | `a.frame(n)`, `a.cycles(n)`, `a.scanlines(n)`, `a.clock()` |
| CPU state | `a.regs()` -> `PC/A/X/Y/S/P` as hex strings, plus `cycles`, `mode` |
| Memory read | `a.peek(addr, len)` -> bytes, `a.peek16(addr)` -> int, `a.memdump(addr, len)` -> bytes |
| Memory write | `a.poke(addr, val)`, `a.poke16(addr, val)`, `a.hwpoke(addr, val)`, `a.memload(addr, data)` |
| Chip state | `a.hwstate()`, `a.antic()`, `a.gtia()`, `a.pokey()`, `a.pia()` |
| Video state | `a.dlist()`, `a.palette()` (768-byte RGB), `a.pmg()`, `a.audio_state()`, `a.screen_text()` |
| Input | `a.joy(port, direction, fire=False)`, `a.key(name, shift=, ctrl=)`, `a.type(text)`, `a.key_raw(name, down=, shift=, ctrl=)`, `a.consol(start=, select=, option=)` |
| Media | `a.boot(path)`, `a.boot_bare()`, `a.mount(drive, path)`, `a.cold_reset()`, `a.warm_reset()`, `a.fresh()` |
| Devices | `a.device_list()`, `a.device_get(tag)`, `a.device_set(tag, enabled, **settings)`, `a.device_remove(tag)`, `a.enable_modern_addons()` |
| Save states | `a.state_save(path)`, `a.state_save(slot="name")`, `a.state_save(inline=True)`, `a.state_load(...)`, `a.state_list()`, `a.state_drop("name")`, `a.checkpoint()` |
| Screenshot | `a.screenshot()` -> PNG bytes; `a.screenshot(path=...)`; `a.rawscreen()` -> 336x240 XRGB8888 (`RawFrame.pixels_rgba()`) |
| Disassembly | `a.disasm(addr, count=8)` -> list of `{addr, bytes, text, next}` |
| Debugger | `a.history(n)`, `a.eval_expr(expr)`, `a.callstack(n)`, `a.memmap()`, `a.bank_info()`, `a.cart_info()` |
| Breakpoints | `a.bp_set(addr, condition=None)`, `a.bp_clear(id)`, `a.bp_list()`, `a.watch_set(addr, mode="r"/"w"/"rw")` |
| Symbols / search | `a.sym_load(path)`, `a.sym_resolve(name)`, `a.sym_lookup(addr)`, `a.memsearch(pattern, start, end)` |
| Profiler | `a.profile_start(mode="insns")`, `a.frame(n)`, `a.profile_stop()`, `a.profile_dump(top=20)`, `a.profile_dump_tree()` |
| Batch / wait | `a.macro([{"boot": {"path": "game.xex"}}, {"wait_text": {"text": "READY", "timeout_frames": 600}}, ...])`; `wait_expr` polls `eval_expr` |

Notes on the table:

- `joy` ports are `0..3`; directions are `centre`, `up`, `down`, `left`, `right`,
  `upleft`, `upright`, `downleft`, `downright`.
- `boot()` accepts XEX/ATR/CAS/CAR/BIN; `mount()` attaches a disk image to
  drive `0..14` (0 = D1).
- `key()` uses POKEY's cooked queue and waits for the keyboard IRQ. Use
  `key_raw()` for programs that poll `SKSTAT`/`KBCODE` with IRQs off (setup
  screens, some games).
- `watch_set(mode="rw")` creates **two** breakpoints and returns two ids.
  Range watches are not supported; set one per address.
- Breakpoint condition expressions use Altirra's evaluator: lowercase register
  names, `db()` / `dw()` for memory, symbols, arithmetic. The Python SDK quotes
  the condition; on the raw wire quote the whole `condition=...` token if it
  contains spaces.
- `profile_dump*()` requires `profile_stop()` first and is one-shot per session;
  restart the profiler for a fresh report.
- `disasm()` wraps Altirra's own disassembler (symbols, 65C816 mode, illegal
  opcodes); do not build a client-side 6502 disassembler.
- `memsearch` scans the CPU view (banking-aware) and caps at 1024 hits.
- `screen_text()` decodes only ANTIC text modes 2/3/6/7; graphics-mode screens
  return `[]` (use a screenshot).

## Configuration and video

```python
a.config()                        # all keys
a.config("video", "ntsc")         # PAL default; ntsc/secam/pal60/ntsc50; cold reset
a.config("machine", "800")        # 800/800XL/1200XL/130XE/XEGS/1400XL/5200; cold reset
a.config("memory", "48K")         # 8K..1088K; cold reset
a.config("basic", "false")        # no cold reset
a.config("artifact", "none")      # none/ntsc/ntschi/pal/palhi/auto/autohi
a.config("debugbrkrun", "true")   # break at EXE run address
```

- Hardware/memory/video changes trigger a cold reset while preserving the pause
  state.
- `a.config_many(machine="800XL", video="pal")` issues one call per key and
  cold-resets once per reset-triggering key; prefer separate explicit calls if
  you care about reset order.
- `a.boot_bare()` boots a tiny stub that disables IRQs/NMIs and ANTIC DMA, parks
  the CPU, and leaves a blank canvas. Useful for display/ANTIC experiments.
- `a.fresh()` is a factory reset that clears breakpoints, watches, symbols,
  profiler, verifier and mounted media, then cold-resets. Good between agent
  iterations.

## Rendering

- Frame buffer is always **336 x 240** in the bridge API.
- `a.screenshot()` returns PNG bytes; `a.screenshot(path=...)` writes on the
  server side.
- `a.rawscreen()` returns little-endian XRGB8888; bytes on the wire are
  `B, G, R, 0`. `RawFrame.pixels_rgba()` reorders for PIL.
- Games may use only 256x240 of the 320x240 display; crop or inspect the
  display list if exact geometry matters.

### River-row capture and display order

- Break at `$AB80`, the first instruction after the row renderer.  Dump zero
  page, the object arrays, and the row at the LMS operand `$3F04/$3F05`.
  Clear the breakpoint before stepping off the same PC.
- Rows are captured in **generation order (oldest first)**, but the live
  screen shows the **newest row at the top** and scrolls down.  A
  top-to-bottom render of `river_rows_157.bin` is therefore vertically
  inverted relative to gameplay.
- A tree is a template fragment: `$BC` bytes wide (4*$BC px), `$BE` rows
  tall, copied one `$BC`-byte row per scanline.  It can start on an odd byte.
  The captured rows 11..32 are a 32-px x 22-row feature (`$BC=8`, offset 4,
  template `$BD12`), with template rows 21..0 matching the capture.
- `tools/river_model.py` is the validated generator reference;
  `tools/atari_river_trace.py` captures the per-row trace;
  `tools/river_validate.py` compares model state and rows against it.

## Altirra GUI (manual inspection)

- Launch: `F:\Emu\Atari800\Altirra\Altirra64.exe`
- Useful command line (reference invocation):
  `Altirra64.exe /w /pal /artifact:none /run "C:\path\to\game.xex"`
  (`/pal` = PAL timing, `/artifact:none` = no artifacting.)
- **View > Adjust Colors**: `Default PAL`, `XL/XE` luma map, `None` colour
  matching, gamma `1.00`. **File > Export Palette** writes a 768-byte Atari800
  palette file.
- **F8** opens the debugger. Enter `a8` for Atari800-compatible monitor
  commands. Typical room-select recipe for Robbo:
  `c 9d NN`, `setpc 1d22`, `sets fd`, `cont` (NN = zero-based level in hex).
- Load MADS/label files via the bridge's `SYM_LOAD` (`.lab`, `.lbl`, `.lst`,
  `.sym`) so `DISASM`/`EVAL` resolve names.
- GTIA ignores colour-register bit 0: odd colour values alias the preceding
  even value.
- Colour reference nuance: the workspace's GBC palette work used **Altirra 4.10
  Default PAL**; the installed GUI is 4.40. If exact historical colours matter,
  use the existing committed 4.10 export rather than re-exporting from 4.40.
- PAL is the faithful reference for Robbo (Polish LK Avalon game). The same
  register bytes look bluer/darker under NTSC.

## Worked reference: Robbo

Original executable:
`C:\dev\AI\robbo-port2\robbo-atari-og-source\bin\robbo.xex`

| Item | Address / value |
|---|---|
| Title code base / entry | `$3800` / `$3883` |
| `CONGR` routine | `$39B6` |
| Display list | `$3CD7` |
| Playfield / screen memory | `$B800` |
| `I.FNT` loaded at | `$1800` |
| Big R/o/D logo glyphs | `I.FNT + $3E8` |

- Title typewriter is settled around frame **2700** after `boot()`; after about
  **5000** frames the attract/demo starts.
- A full title frame is 256x240 content inside a 320x240 display.
- `d1/TITLE.ASM` is the source for title routines; `d1/R1.ASM` has `CNUM`/`SETU`
  for the room-select debugger recipe. Verify addresses against the assembled
  label table if the executable changes.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Black or wrong screenshot | Program not loaded yet: wait more frames (`frame(300)`+), check `a.config()` and `a.regs()`, inspect the server `.log`. |
| Server appears to hang after several commands | Its stderr pipe is full. If launched with `stderr=PIPE`, keep draining it for the whole session or redirect stderr to a file. |
| `AuthError` | Stale token file from a previous server; read the new one. |
| Connection reset / EOF | Server exited (`quit`, crash, port conflict); inspect the `.log`. |
| Injected keys ignored | Program polls the matrix with IRQs off; use `a.key_raw()` instead of `a.key()`. |
| `frame()` seems not to return | It returns; the *next* command waits for the gate. Ensure the gate count is valid and the server is advancing. |
| State reads are all reset values | `boot()` only armed the loader; wait frames. Also check `--settings=user` did not select an unexpected profile. |
| Save state loads paused | `state_load` preserves pause state; call `a.resume()`. |
| Multiple clients fail | The server accepts one client at a time. Use one connection/thread. |

## Cleanup

```powershell
# If a.quit() was not used:
Stop-Process -Id <server-pid>
```

Remove temporary screenshots/logs when finished. Do not commit token files.
If another agent owns the server, use `a.close()` instead of `a.quit()` so you
do not terminate their session.

## Reference files

- Package: `F:\Emu\Atari800\Altirra\AlitrraBridge\README.md`,
  `docs\COMMANDS.md`, `docs\PROTOCOL.md`, `docs\GETTING_STARTED.md`.
- Python recipes: `skills\altirra-bridge\references\python-quickstart.md`.
- RE workflows and case studies: `skills\altirra-bridge\references\workflows.md`,
  `examples\case_studies\`.
