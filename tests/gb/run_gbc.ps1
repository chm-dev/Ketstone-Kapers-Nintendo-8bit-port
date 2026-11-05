<#
.SYNOPSIS
  Gearboy smoke run of the GBC ROM: takes build/gearboy.lock, starts a headless Gearboy (MCP on -Port),
  runs tests/gb/shots.mjs with a JSON step list (press/release/tap/wait/poke/peek/shot), stops Gearboy
  and frees the lock.  Screenshots land where the steps say (use build/gbc_shots/).
.EXAMPLE
  pwsh tests/gb/run_gbc.ps1 tests/gb/smoke_steps.json        (GBC)
  pwsh tests/gb/run_gbc.ps1 tests/gb/smoke_steps.json -Dmg   (DMG ROM, forced DMG mode, shots in build/dmg_shots/)
#>
param([Parameter(Mandatory)][string]$Steps, [string]$Rom = 'roms/keystone_kapers', [int]$Port = 7791,
      [switch]$Dmg)   # -Dmg: roms/keystone_kapers.gb on a Gearboy copy with ForceDMG = true; shots go to build/dmg_shots/
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
    # --portable: read gearboy/config.ini (ForceDMG = false).  Without it Gearboy booted the CGB-only ROM as a
    # DMG (_cpu = $01), and the ROM stopped at its "needs a GBC" screen.
    $exe = 'gearboy/Gearboy.exe'
    $ext = 'gbc'
    if ($Dmg) {
        # a private copy of Gearboy (portable config next to the exe) with ForceDMG = true: the shared gearboy/config.ini stays untouched
        $ext = 'gb'
        $dd = Join-Path $root 'build\gearboy_dmg'
        if (-not (Test-Path (Join-Path $dd 'Gearboy.exe'))) {
            New-Item -ItemType Directory -Force $dd | Out-Null
            Copy-Item gearboy\Gearboy.exe, gearboy\SDL3.dll, gearboy\config.ini, gearboy\gamecontrollerdb.txt $dd
            Copy-Item gearboy\shaders -Destination $dd -Recurse -ErrorAction SilentlyContinue
            (Get-Content (Join-Path $dd 'config.ini')) -replace '^ForceDMG = false', 'ForceDMG = true' | Set-Content (Join-Path $dd 'config.ini')
        }
        $exe = Join-Path $dd 'Gearboy.exe'
        $tmp = Join-Path $root 'build\dmg_steps.json'
        (Get-Content $Steps -Raw) -replace 'gbc_shots', 'dmg_shots' | Set-Content $tmp
        $Steps = $tmp
    }
    elseif (-not (Select-String 'gearboy/config.ini' -Pattern '^ForceDMG = false' -Quiet)) { throw 'gearboy/config.ini: ForceDMG is not false' }
    $emu = Start-Process -FilePath $exe -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir 'out.txt') -RedirectStandardError (Join-Path $logDir 'err.txt') `
        -ArgumentList '--portable', '--headless', '--mcp-http', '--mcp-http-port', $Port, "$Rom.$ext", $(if ($Dmg) { "$($Rom)_dmg.noi" } else { "$Rom.noi" })
    $env:GEARBOY_MCP_URL = "http://127.0.0.1:$Port/mcp"
    $env:GB_NOI = if ($Dmg) { "$($Rom)_dmg.noi" } else { "$Rom.noi" }
    Start-Sleep 3
    node tests/gb/shots.mjs run $Steps
    $code = $LASTEXITCODE
}
finally {
    if ($emu -and -not $emu.HasExited) { Stop-Process -Id $emu.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item -Recurse -Force $lock -ErrorAction SilentlyContinue
}
exit $code
