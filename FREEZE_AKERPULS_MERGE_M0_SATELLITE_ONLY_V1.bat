@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "SOURCE=C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_v1"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1"
if not "%~1"=="" set "SOURCE=%~1"
if not "%~2"=="" set "OUT=%~2"

echo ============================================================
echo AKERPULS - FREEZE MERGE M0 SATELLITE-ONLY V1
echo EXACT FULL-SKANE BASELINE BEFORE AKERMINNE/M4
echo ============================================================
echo SOURCE=%SOURCE%
echo OUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before M0 freeze.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)

if not exist "%SOURCE%\m0_satellite_merge_manifest.json" (echo ERROR: missing M0 source manifest& exit /b 1)
if not exist "%SOURCE%\m0_satellite_merge_pairs.csv" (echo ERROR: missing M0 source CSV& exit /b 1)

echo.
echo [1/2] Unit tests
py -3 -m unittest tests.test_akerpuls_merge_m0_satellite_only_freeze_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Freeze exact satellite-only M0 package
py -3 -u src\171_akerpuls_merge_m0_satellite_only_freeze_v1.py --source-dir "%SOURCE%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\AKERPULS_MERGE_M0_SATELLITE_ONLY_FREEZE_V1.json" (echo ERROR: M0 freeze JSON not created& exit /b 1)
if not exist "%OUT%\akerpuls_merge_m0_satellite_only_freeze_manifest.json" (echo ERROR: M0 freeze manifest not created& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during M0 freeze.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: satellite-only merge M0 formally frozen.
echo No AkerMinne/M4/fusion or geometry mutation was executed.
echo OUTPUT=%OUT%
echo NEXT STOP: build M1 AkerMinne/M4 pair prior on exact frozen M0 universe.
echo ============================================================
exit /b 0
