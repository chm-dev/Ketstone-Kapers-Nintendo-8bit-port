<#
.SYNOPSIS
  Gearboy smoke run of the GB ROM (one ROM for both machines): takes build/gearboy.lock, starts a headless
  Gearboy (MCP on -Port), runs tests/gb/shots.mjs with a JSON step list (press/release/tap/wait/poke/peek/
  shot), stops Gearboy and frees the lock.  Screenshots land where the steps say (use build/gbc_shots/).
  Default: CGB mode (gearboy/config.ini ForceDMG = false).  -Dmg: the SAME ROM on a private Gearboy copy
  with ForceDMG = true (original Game Boy; the ROM takes its DMG shade path), "gbc_shots" in the step
  paths rewritten to "dmg_shots".  Add {"peek": "_gb_color"} to a step list to see the path taken (01 / 00).
.EXAMPLE
  pwsh tests/gb/run_gbc.ps1 tests/gb/smoke_steps.json        (Game Boy Color)
  pwsh tests/gb/run_gbc.ps1 tests/gb/smoke_steps.json -Dmg   (original Game Boy, shots in build/dmg_shots/)
#>
param([Parameter(Mandatory)][string]$Steps, [string]$Rom = 'roms/keystone_kapers', [int]$Port = 7791,
      [switch]$Dmg)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Set-Location $root
$lock = Join-Path $root 'build\gearboy.lock'
New-Item -ItemType Directory -Force (Join-Path $root 'build\gbc_shots'), (Join-Path $root 'build\dmg_shots') | Out-Null
$got = $false
for ($i = 0; $i -lt 120 -and -not $got; $i++) {
    try { New-Item -ItemType Directory -Path $lock -ErrorAction Stop | Out-Null; $got = $true }
    catch { if ($i % 12 -eq 0) { Write-Host "waiting for $lock ..." }; Start-Sleep -Seconds 5 }
}
if (-not $got) { throw "could not take $lock" }
$emu = $null
try {
    $logDir = Join-Path $root 'build\gearboy_log'
    New-Item -ItemType Directory -Force $logDir | Out-Null
    # --portable: read the config.ini next to the exe (ForceDMG).  Without it Gearboy may pick the machine
    # itself (a CGB-only ROM once booted as a DMG here).
    $exe = 'gearboy/Gearboy.exe'
    if ($Dmg) {
        # a private copy of Gearboy (portable config next to the exe) with ForceDMG = true: the shared gearboy/config.ini stays untouched
        $dd = Join-Path $root 'build\gearboy_dmg'
        if (-not (Test-Path (Join-Path $dd 'Gearboy.exe'))) {
            New-Item -ItemType Directory -Force $dd | Out-Null
            Copy-Item gearboy\Gearboy.exe, gearboy\SDL3.dll, gearboy\config.ini, gearboy\gamecontrollerdb.txt $dd
            Copy-Item gearboy\shaders -Destination $dd -Recurse -ErrorAction SilentlyContinue
        }
        $cfg = Join-Path $dd 'config.ini'
        (Get-Content $cfg) -replace '^ForceDMG = false', 'ForceDMG = true' | Set-Content $cfg
        if (-not (Select-String $cfg -Pattern '^ForceDMG = true' -Quiet)) { throw "$cfg`: ForceDMG is not true" }
        $exe = Join-Path $dd 'Gearboy.exe'
        $tmp = Join-Path $root 'build\dmg_steps.json'
        (Get-Content $Steps -Raw) -replace 'gbc_shots', 'dmg_shots' | Set-Content $tmp
        $Steps = $tmp
    }
    elseif (-not (Select-String 'gearboy/config.ini' -Pattern '^ForceDMG = false' -Quiet)) { throw 'gearboy/config.ini: ForceDMG is not false' }
    $noi = "$($Rom)_gb.noi"
    $emu = Start-Process -FilePath $exe -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir 'out.txt') -RedirectStandardError (Join-Path $logDir 'err.txt') `
        -ArgumentList '--portable', '--headless', '--mcp-http', '--mcp-http-port', $Port, "$Rom.gbc", $noi
    $env:GEARBOY_MCP_URL = "http://127.0.0.1:$Port/mcp"
    $env:GB_NOI = $noi
    Start-Sleep 3
    node tests/gb/shots.mjs run $Steps
    $code = $LASTEXITCODE
}
finally {
    if ($emu -and -not $emu.HasExited) { Stop-Process -Id $emu.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item -Recurse -Force $lock -ErrorAction SilentlyContinue
}
exit $code
