param(
    [string]$DownloaderDir = 'C:\AkerSyncDEM',
    [string]$RepoDir = 'C:\AkerSyncRepo',
    [string]$OutputDir = 'C:\AkerSyncRaw\dem_skane_2p5km'
)

$ErrorActionPreference = 'Stop'

$source = Join-Path $DownloaderDir 'download_dem.ps1'
$target = Join-Path $DownloaderDir 'download_dem_skane.ps1'
$missingTxt = Join-Path $RepoDir 'data\derived\dem_missing_skane_2p5km.txt'
$wantedCsv = Join-Path $DownloaderDir 'wanted_tiles_skane.csv'

if (-not (Test-Path $source)) { throw "Saknar originalnedladdaren: $source" }
if (-not (Test-Path $missingTxt)) { throw "Saknar Skåne-listan: $missingTxt" }

$files = @(Get-Content $missingTxt | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($files.Count -ne 367) {
    throw "Väntade 367 saknade DEM-filer, fick $($files.Count). Kör PLAN_SKANE_DEM.bat igen först."
}

# Create a dedicated CSV for the Skåne downloader. Leave yesterday's files untouched.
@('filename;municipalities') + ($files | ForEach-Object { "$_;Skane" }) |
    Set-Content -Path $wantedCsv -Encoding UTF8

$lines = Get-Content $source
$out = New-Object System.Collections.Generic.List[string]
$mode = 'normal'
$areasDone = $false
$wantedDone = $false

foreach ($line in $lines) {
    if ($mode -eq 'areas') {
        if ($line.Trim() -eq '}') { $mode = 'normal' }
        continue
    }
    if ($mode -eq 'wanted') {
        if ($line.Trim() -eq '}') { $mode = 'normal' }
        continue
    }

    if ($line -match '^\s*\[string\]\$OutputDir\s*=') {
        $out.Add(('    [string]$OutputDir = ''{0}''' -f $OutputDir))
        continue
    }

    if ($line -match '^\$Areas\s*=\s*\[ordered\]@\{') {
        # WGS84 envelope of the verified 2.5 km rectangle
        # EPSG:3006 bbox: 362500,6152500,420000,6217500.
        $out.Add('$Areas = [ordered]@{')
        $out.Add('    "Skane" = @(12.7904, 55.4992, 13.7332, 56.0959)')
        $out.Add('}')
        $mode = 'areas'
        $areasDone = $true
        continue
    }

    if ($line -match '^\$WantedTiles\s*=\s*\[ordered\]@\{') {
        $out.Add('$WantedTiles = [ordered]@{}')
        $out.Add('$wantedCsv = Join-Path $PSScriptRoot "wanted_tiles_skane.csv"')
        $out.Add('foreach ($row in (Import-Csv -Path $wantedCsv -Delimiter ";")) {')
        $out.Add('    $WantedTiles[[string]$row.filename] = [string]$row.municipalities')
        $out.Add('}')
        $mode = 'wanted'
        $wantedDone = $true
        continue
    }

    if ($line -match '^\$outPath\s*=\s*Join-Path\s+\(Get-Location\)\s+\$OutputDir\s*$') {
        $out.Add('if ([System.IO.Path]::IsPathRooted($OutputDir)) {')
        $out.Add('    $outPath = $OutputDir')
        $out.Add('} else {')
        $out.Add('    $outPath = Join-Path (Get-Location) $OutputDir')
        $out.Add('}')
        continue
    }

    $out.Add($line)
}

if (-not $areasDone) { throw 'Kunde inte hitta $Areas-blocket i v1.9-scriptet.' }
if (-not $wantedDone) { throw 'Kunde inte hitta $WantedTiles-blocket i v1.9-scriptet.' }

$out | Set-Content -Path $target -Encoding UTF8

$listBat = Join-Path $DownloaderDir 'BARA_LISTA_SKANE.bat'
@"
@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo AkerSync DEM v1.9 - SKANE - BARA LISTA
echo ============================================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0download_dem_skane.ps1" -ListOnly
echo.
pause
"@ | Set-Content -Path $listBat -Encoding ASCII

$startBat = Join-Path $DownloaderDir 'STARTA_SKANE.bat'
@"
@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo AkerSync DEM v1.9 - SKANE - LADDA NER
 echo Output: $OutputDir
echo ============================================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0download_dem_skane.ps1"
echo.
pause
"@ | Set-Content -Path $startBat -Encoding ASCII

Write-Host ('='*72)
Write-Host 'ÅkerSync · Skåne-downloader förberedd'
Write-Host ('='*72)
Write-Host "Saknade filer i wanted-listan: $($files.Count)"
Write-Host "Källa (orörd):              $source"
Write-Host "Skåne-kopia:                $target"
Write-Host "Wanted CSV:                 $wantedCsv"
Write-Host "Output:                     $OutputDir"
Write-Host "Torrkörning:                 $listBat"
Write-Host "Nedladdning:                 $startBat"
Write-Host ''
Write-Host 'Kör BARA_LISTA_SKANE.bat först. STARTA_SKANE.bat först efter kontroll.'
