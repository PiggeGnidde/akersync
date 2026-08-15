@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "CFG=%CD%\config\local_paths.json"
set "NEWDEM=C:\AkerSyncRaw\dem_skane_2p5km"

if not exist "%CFG%" (
  echo SAKNAS: %CFG%
  exit /b 1
)
if not exist "%NEWDEM%" (
  echo SAKNAS: %NEWDEM%
  exit /b 1
)

copy /Y "%CFG%" "%CFG%.before_skane_dem.bak" >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p='%CFG%'; $j=Get-Content -Raw -LiteralPath $p | ConvertFrom-Json; $old=$j.dem_dir; $j.dem_dir='%NEWDEM%'; $txt=$j | ConvertTo-Json -Depth 20; [System.IO.File]::WriteAllText($p,$txt,(New-Object System.Text.UTF8Encoding($false))); Write-Host ('dem_dir: ' + $old + '  ->  ' + $j.dem_dir)"
if errorlevel 1 exit /b 1

echo Backup: %CFG%.before_skane_dem.bak
echo.
echo Skane DEM konfigurerad. Kor CHECK_INPUTS.bat som nasta steg.
