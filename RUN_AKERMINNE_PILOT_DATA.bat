@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "LOGDIR=data\derived\akerminne_v1a\logs"
set "LOG=%LOGDIR%\akerminne_pilot_download.log"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

where py >nul 2>&1
if errorlevel 1 (
  echo FEL: Python launcher "py" saknas.
  exit /b 1
)

echo ==============================================================================
echo AkerMinne v1a - hamta historisk Skurup-pilot 2015 + 2020
echo ==============================================================================
echo.

py -3 src\51_download_akerminne_pilot.py --years 2015 2020 > "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
type "%LOG%"
if not "%RC%"=="0" (
  echo.
  echo ==============================================================================
  echo PILOT DATA RUNNER: FAIL ^(exit %RC%^)
  echo Logg: %LOG%
  echo ==============================================================================
  exit /b %RC%
)

if not exist "C:\AkerSyncRaw\akerminne_v1a\2015\arslager_block_skurup_2015.gpkg" goto missing
if not exist "C:\AkerSyncRaw\akerminne_v1a\2015\arslager_skifte_skurup_2015.gpkg" goto missing
if not exist "C:\AkerSyncRaw\akerminne_v1a\2020\arslager_block_skurup_2020.gpkg" goto missing
if not exist "C:\AkerSyncRaw\akerminne_v1a\2020\arslager_skifte_skurup_2020.gpkg" goto missing

echo.
echo ==============================================================================
echo PILOT DATA RUNNER: PASS
echo ==============================================================================
echo Nasta kommando: CALL RUN_AKERMINNE_DISCOVERY.bat
exit /b 0

:missing
echo.
echo FEL: nedladdaren returnerade 0 men en eller flera pilotfiler saknas.
echo PILOT DATA RUNNER: FAIL
exit /b 2
