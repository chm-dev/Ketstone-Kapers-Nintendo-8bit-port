<#
.SYNOPSIS
  Gearboy smoke run of the GBC ROM: takes build/gearboy.lock, starts a headless Gearboy (MCP on -Port),
  runs tests/gb/shots.mjs with a JSON step list (press/release/tap/wait/poke/peek/shot), stops Gearboy
  and frees the lock.  Screenshots land where the steps say (use build/gbc_shots/).
.EXAMPLE
  pwsh tests/gb/run_gbc.ps1 tests/gb/smoke_steps.json
#>
param([Parameter(Mandatory)][string]$Steps, [string]$Rom = 'roms/keystone_kapers', [int]$Port = 7791)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Set-Location $root
$lock = Join-Path $root 'build\gearboy.lock'
New-Item -ItemType Directory -Force (Join-Path $root 'build\gbc_shots') | Out-Null
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
    if (-not (Select-String 'gearboy/config.ini' -Pattern '^ForceDMG = false' -Quiet)) { throw 'gearboy/config.ini: ForceDMG is not false' }
    $emu = Start-Process -FilePath gearboy/Gearboy.exe -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir 'out.txt') -RedirectStandardError (Join-Path $logDir 'err.txt') `
        -ArgumentList '--portable', '--headless', '--mcp-http', '--mcp-http-port', $Port, "$Rom.gbc", "$Rom.noi"
    $env:GEARBOY_MCP_URL = "http://127.0.0.1:$Port/mcp"
    $env:GB_NOI = "$Rom.noi"
    Start-Sleep 3
    node tests/gb/shots.mjs run $Steps
    $code = $LASTEXITCODE
}
finally {
    if ($emu -and -not $emu.HasExited) { Stop-Process -Id $emu.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item -Recurse -Force $lock -ErrorAction SilentlyContinue
}
exit $code
