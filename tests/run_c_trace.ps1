<#
.SYNOPSIS
  Golden-trace check of the C engine: builds the DEBUG_TRACE ROM, starts MesenCE-MCP (holding
  the build/mesen.lock dir), replays every golden scenario (tests/c_trace.mjs) and stops Mesen.
.EXAMPLE
  pwsh tests/run_c_trace.ps1            # all scenarios
  pwsh tests/run_c_trace.ps1 kop_b esc0 # some scenarios
#>
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Scenarios)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$lock = Join-Path $root 'build\mesen.lock'
$mesen = Join-Path $root 'MesenCE-MCP\MesenCE-MCP-Windows.exe'
$rom = Join-Path $root 'roms\keystone_kapers_trace.nes'

& (Join-Path $root 'build.ps1') -Trace | Out-Null
if (-not (Test-Path $rom)) { throw 'trace ROM not built' }

New-Item -ItemType Directory -Force (Join-Path $root 'build') | Out-Null
$got = $false
for ($i = 0; $i -lt 360 -and -not $got; $i++) {
    try { New-Item -ItemType Directory -Path $lock -ErrorAction Stop | Out-Null; $got = $true }
    catch { if ($i % 12 -eq 0) { Write-Host "waiting for $lock ..." }; Start-Sleep -Seconds 5 }
}
if (-not $got) { throw "could not take $lock" }

$p = $null
$code = 1
try {
    $logDir = Join-Path $root 'build\mesen_log'
    New-Item -ItemType Directory -Force $logDir | Out-Null
    $out = Join-Path $logDir 'mesen.out'; $err = Join-Path $logDir 'mesen.err'
    Remove-Item $out, $err -ErrorAction SilentlyContinue
    $p = Start-Process $mesen -ArgumentList '--mcp', '--mcp-port=9100', '--enableStdout', '--doNotSaveSettings',
        '--preferences.pauseWhenInBackground=false', '--preferences.pauseWhenInMenusAndConfig=false',
        '--emulation.emulationSpeed=0', '--nes.region=Ntsc', "`"$rom`"" `
        -WorkingDirectory $root -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
    $ready = $false
    for ($i = 0; $i -lt 120 -and -not $ready; $i++) {
        if ($p.HasExited) { throw "Mesen exited early; see $out / $err" }
        foreach ($f in $out, $err) {
            if ((Test-Path $f) -and (Select-String $f -Pattern 'MCP server started on port' -Quiet)) { $ready = $true }
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) { throw "Mesen MCP did not start; see $out / $err" }
    & node (Join-Path $root 'tests\c_trace.mjs') $rom @Scenarios
    $code = $LASTEXITCODE
}
finally {
    if ($p -and -not $p.HasExited) {
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        $p.WaitForExit(10000) | Out-Null
    }
    Remove-Item -Recurse -Force $lock -ErrorAction SilentlyContinue
}
exit $code
