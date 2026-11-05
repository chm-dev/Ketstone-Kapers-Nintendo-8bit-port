<#
.SYNOPSIS
  Build the Keystone Kapers NES port with GBDK-2020.

.DESCRIPTION
  Compiles every src/*.c file into build/obj, links roms/keystone_kapers.nes,
  keeps the .noi/.map debug artifacts, and validates the iNES header and
  the internal-RAM layout before reporting success.

  GBDK 4.5.0's NES target requires the explicit -mmos6502:nes spelling;
  the shorter -mnes form is rejected.  -Wl-j emits the .noi symbol file
  used by tests/nes_smoke.mjs.

.PARAMETER Clean
  Delete build/ and the generated ROM/NOI/map files first.

.PARAMETER Trace
  Build the golden-trace debug ROM (-DDEBUG_TRACE, scripted input + trace ring, see
  src/trace.h) as roms/keystone_kapers_trace.nes; used by tests/run_c_trace.ps1.

.PARAMETER Profile
  Export the statics of river.c and entities.c as .noi symbols, for the perf_*
  scripts that split costs by function or read river_job.

.EXAMPLE
  ./build.ps1
  ./build.ps1 -Clean
#>
[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$Profile,
    [switch]$Trace
)

$ErrorActionPreference = 'Stop'

$repoRoot = $PSScriptRoot
$gbdk     = Join-Path $repoRoot 'gbdk'
$lcc      = Join-Path $gbdk 'bin\lcc.exe'
$srcRoot  = Join-Path $repoRoot 'src'
$buildDir = Join-Path $repoRoot 'build'
$romBase  = if ($Trace) { 'keystone_kapers_trace' } else { 'keystone_kapers' }
$objDir   = Join-Path $buildDir $(if ($Trace) { 'obj_trace' } else { 'obj' })
$romDir   = Join-Path $repoRoot 'roms'
$romPath  = Join-Path $romDir "$romBase.nes"
$noiPath  = Join-Path $romDir "$romBase.noi"
$mapPath  = Join-Path $romDir "$romBase.map"

if (-not (Test-Path $lcc)) {
    throw "GBDK lcc not found at $lcc"
}
if (-not (Test-Path $srcRoot)) {
    throw "Source directory not found at $srcRoot"
}

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $buildDir
    Remove-Item -Force -ErrorAction SilentlyContinue @(
        $romPath, $noiPath, $mapPath,
        (Join-Path $romDir "$romBase.ihx"),
        (Join-Path $romDir "$romBase.rom")
    )
}

New-Item -ItemType Directory -Force -Path $objDir, $romDir | Out-Null

# -Wf flags go to the compiler, -Wm to makenes and -Wl to the linker.
$compileFlags = @(
    '-mmos6502:nes'
    "-I$srcRoot"
    '-Wf--opt-code-size'
)
if ($Profile) { $compileFlags += '-DPROF_EXPORT_STATICS' }
if ($Trace)   { $compileFlags += '-DDEBUG_TRACE' }

$linkFlags = @(
    '-mmos6502:nes'
    "-I$srcRoot"
    '-Wm-yoA'              # auto-size PRG banks for the generated code
    '-Wl-j'                # .noi symbols for Mesen MCP tests
    '-Wl-m'                # .map file
    '-Wf--opt-code-size'
)

$sources = Get-ChildItem -Path $srcRoot -Filter '*.c' -File | Sort-Object Name
if (-not $sources) {
    throw "No C sources found under $srcRoot"
}

$objects = @()
foreach ($src in $sources) {
    $name = [System.IO.Path]::GetFileNameWithoutExtension($src.Name)
    $obj  = Join-Path $objDir "$name.o"
    Write-Host "CC  $($src.Name)"
    [string[]]$bankFlags = @()
    if ($name -eq 'bg_data_a') { $bankFlags = @('-Wf-bo1') }   # screens 0-3 data in PRG bank 1
    if ($name -eq 'bg_data_b') { $bankFlags = @('-Wf-bo2') }   # screens 4-7 data in PRG bank 2
    if ($name -eq 'hud_data') { $bankFlags = @('-Wf-bo1') }   # HUD font/minimap tiles in PRG bank 1
    & $lcc @compileFlags @bankFlags '-c' '-o' $obj $src.FullName
    if ($LASTEXITCODE -ne 0) {
        throw "Compilation failed: $($src.Name)"
    }
    $objects += $obj
}

Write-Host "LD  $romPath"
& $lcc @linkFlags '-o' $romPath @objects
if ($LASTEXITCODE -ne 0) {
    throw 'Link failed'
}

# lcc/makenes leave the intermediate Intel-hex and raw ROM images behind.
Remove-Item -Force -ErrorAction SilentlyContinue @(
    (Join-Path $romDir "$romBase.ihx"),
    (Join-Path $romDir "$romBase.rom")
)

if (-not (Test-Path $romPath)) { throw "ROM not produced: $romPath" }
if (-not (Test-Path $noiPath)) { throw "NOI not produced: $noiPath" }

# GBDK 4.5.0 always passes `makenes -a 1` (four-screen layout bit).  This
# port needs the two vertically stacked nametables that horizontal mirroring
# provides: HUD in $2000, playfield ring in $2800.
$patchHeader = Join-Path $repoRoot 'tools\patch_nes_header.py'
if (-not (Test-Path $patchHeader)) { throw "Header patch tool missing: $patchHeader" }
& python $patchHeader $romPath
if ($LASTEXITCODE -ne 0) { throw 'NES header patch failed' }

function Get-NoiSymbol {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $match = Select-String -Path $Path -Pattern "^DEF $([regex]::Escape($Name)) 0x([0-9A-Fa-f]+)$"
    if (-not $match) {
        throw "Symbol '$Name' not found in $Path"
    }
    return [Convert]::ToInt32($match.Matches[0].Groups[1].Value, 16)
}

function Assert-RomHeader {
    param([Parameter(Mandatory = $true)][string]$Path)

    $rom = [System.IO.File]::ReadAllBytes($Path)
    if ($rom.Length -lt 16) {
        throw "ROM is shorter than an iNES header: $Path"
    }
    if ($rom[0] -ne 0x4E -or $rom[1] -ne 0x45 -or
        $rom[2] -ne 0x53 -or $rom[3] -ne 0x1A) {
        throw "Missing iNES magic: $Path"
    }

    $prgBanks = [int]$rom[4]
    $chrBanks = [int]$rom[5]
    $mapper   = (($rom[6] -shr 4) -band 0x0F) -bor ($rom[7] -band 0xF0)
    $layout   = $rom[6] -band 0x0F
    $expected = 16 + ($prgBanks * 16384) + ($chrBanks * 8192)

    if ($mapper -ne 30) {
        throw ("Unexpected mapper {0}; GBDK-NES should emit UNROM-512 (30)" -f $mapper)
    }
    if ($chrBanks -ne 0) {
        throw ("Unexpected CHR-ROM bank count {0}; this build uses 8 KiB CHR-RAM" -f $chrBanks)
    }
    if ($layout -ne 1) {
        throw ("Unexpected iNES nametable layout 0x{0:X2}; expected vertical mirroring" -f $layout)
    }
    if ($rom.Length -ne $expected) {
        throw ("ROM size {0} does not match header ({1} bytes)" -f $rom.Length, $expected)
    }

    Write-Host (("ROM  {0} bytes, mapper {1}, PRG {2} x 16 KiB, CHR-RAM, " +
        "vertical mirroring (HUD `$2000 + playfield `$2400)") -f `
        $rom.Length, $mapper, $prgBanks)
}

function Assert-RamLayout {
    param([Parameter(Mandatory = $true)][string]$Noi)

    $dataStart = Get-NoiSymbol -Path $Noi -Name 's__DATA'
    $dataLen   = Get-NoiSymbol -Path $Noi -Name 'l__DATA'
    $bssStart  = Get-NoiSymbol -Path $Noi -Name 's__BSS'
    $bssLen    = Get-NoiSymbol -Path $Noi -Name 'l__BSS'
    $heapStart = Get-NoiSymbol -Path $Noi -Name 's__HEAP'

    $dataEnd = $dataStart + $dataLen
    $bssEnd  = $bssStart + $bssLen

    # GBDK-NES keeps $0000-$00FF zero page, $0100-$01C7 transfer buffer +
    # attribute shadow, $01C8-$01FF hardware stack, and $0200-$02FF OAM
    # shadow.  C data starts at $0300 and must end before internal RAM.
    if ($dataStart -lt 0x0300) {
        throw ("_DATA starts at 0x{0:X4}, below the GBDK RAM base 0x0300" -f $dataStart)
    }
    if ($dataEnd -gt $bssStart) {
        throw ("_DATA ends at 0x{0:X4}, overlapping _BSS at 0x{1:X4}" -f $dataEnd, $bssStart)
    }
    if ($bssEnd -gt 0x0800) {
        throw ("_BSS ends at 0x{0:X4}, past internal RAM 0x07FF" -f $bssEnd)
    }
    if ($heapStart -lt $bssEnd -or $heapStart -gt 0x0800) {
        throw ("_HEAP starts at 0x{0:X4}, outside the free RAM window" -f $heapStart)
    }

    Write-Host ("RAM  DATA 0x{0:X4}-0x{1:X4}, BSS 0x{2:X4}-0x{3:X4}, HEAP 0x{4:X4}, {5} bytes free" -f `
        $dataStart, ($dataEnd - 1), $bssStart, ($bssEnd - 1), $heapStart, (0x0800 - $heapStart))
}

function Assert-FixedBank {
    param([Parameter(Mandatory = $true)][string]$Noi)
    # The linker does not fail when the fixed bank runs into the vectors (river-raid lesson 13).
    $end = 0
    foreach ($area in @('_CODE', '_HOME', '_RODATA', '_XINIT', '_GSINIT', '_GSFINAL')) {
        $s = Select-String -Path $Noi -Pattern "^DEF s_$([regex]::Escape($area)) 0x([0-9A-Fa-f]+)$"
        $l = Select-String -Path $Noi -Pattern "^DEF l_$([regex]::Escape($area)) 0x([0-9A-Fa-f]+)$"
        if ($s -and $l) {
            $e = [Convert]::ToInt32($s.Matches[0].Groups[1].Value, 16) + [Convert]::ToInt32($l.Matches[0].Groups[1].Value, 16)
            if ($e -gt $end) { $end = $e }
        }
    }
    if ($end -gt 0xFFFA) { throw ("Fixed bank ends at 0x{0:X4}, past the vectors at 0xFFFA" -f $end) }
    Write-Host ("BANK fixed bank ends at 0x{0:X4} ({1} bytes free)" -f $end, (0xFFFA - $end))
}

Assert-RomHeader -Path $romPath
Assert-RamLayout -Noi $noiPath
Assert-FixedBank -Noi $noiPath

Write-Host "MAP  $mapPath"
Write-Host "OK   $romPath"
