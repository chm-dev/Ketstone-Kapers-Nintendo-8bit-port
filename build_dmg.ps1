<#
.SYNOPSIS
  Thin wrapper: builds the one Game Boy ROM (build_gbc.ps1; header $80 = colour on a Game Boy Color,
  4 grey shades on an original Game Boy) and copies it to roms/<Name>.gb for DMG emulators / flash carts.

.DESCRIPTION
  There is no separate DMG build any more (DECISIONS_PENDING U1): the DMG shade data (src/dmg/,
  tools/gen_dmg_assets.py) is linked into roms/<Name>.gbc and main_gbc.c picks the path at boot (_cpu).
  roms/<Name>.gb is a byte copy of roms/<Name>.gbc; symbols are roms/<Name>_gb.noi.
  The old roms/<Name>_dmg.map/.noi (separate DMG link) are removed when found.

.EXAMPLE
  .\build_dmg.ps1
#>
[CmdletBinding()]
param(
    [int]$Banks = 8,
    [string]$Name = 'keystone_kapers'
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& (Join-Path $PSScriptRoot 'build_gbc.ps1') -Banks $Banks -Name $Name
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$out = Join-Path $PSScriptRoot 'roms'
Copy-Item -Force (Join-Path $out "$Name.gbc") (Join-Path $out "$Name.gb")
foreach ($old in "$($Name)_dmg.map", "$($Name)_dmg.noi") { Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $out $old) }
Write-Host "OK   $(Join-Path $out "$Name.gb") (copy of $Name.gbc)" -ForegroundColor Green
