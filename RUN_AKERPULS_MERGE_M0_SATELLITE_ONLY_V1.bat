@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "D2C=C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_v1"
if not "%~1"=="" set "D2C=%~1"
if not "%~2"=="" set "OUT=%~2"

echo ============================================================
echo AKERPULS - MERGE M0 SATELLITE-ONLY V1
echo FULL SKANE - SAME-BLOCK TOUCHING 2025 BOUNDARIES
echo NO AKERMINNE / M4 / FUSION
echo ============================================================
echo D2C=%D2C%
echo OUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before M0 merge discovery.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)

if not exist "%D2C%\akerpuls_preliminary_geometry_v1_freeze\AKERPULS_PRELIMINARY_GEOMETRY_V1_FREEZE.json" (
  echo ERROR: missing frozen AkerPuls preliminary geometry v1
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_d2a_full_skane_split_discovery_v1\d2a_manifest.json" (
  echo ERROR: missing frozen D2A full-Skane result
  exit /b 1
)

echo.
echo [1/2] Unit tests
py -3 -m unittest tests.test_akerpuls_merge_m0_satellite_only_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Run full-Skane satellite-only merge discovery
py -3 -u src\169_akerpuls_merge_m0_satellite_only_v1.py --d2c-dir "%D2C%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\m0_satellite_merge_pairs.csv" (echo ERROR: M0 pair CSV not created& exit /b 1)
if not exist "%OUT%\m0_satellite_merge_boundaries.gpkg" (echo ERROR: M0 boundary GPKG not created& exit /b 1)
if not exist "%OUT%\M0_SATELLITE_ONLY_MERGE_SUMMARY_V1.json" (echo ERROR: M0 summary not created& exit /b 1)
if not exist "%OUT%\m0_satellite_merge_manifest.json" (echo ERROR: M0 manifest not created& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during M0 merge discovery.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: satellite-only merge M0 completed and stopped for review.
echo No AkerMinne/M4/fusion or geometry mutation was executed.
echo OUTPUT=%OUT%
echo NEXT STOP: inspect census and score distribution before M1 prior.
echo ============================================================
exit /b 0
