@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "EXPECTED_TAG=akerpuls-split-fusion-qa-v1.0"
set "EXPECTED_FREEZE_COMMIT=bd8ef176ffdb1c29c2db42bcdbf83fb4bdca8899"
set "OUT=C:\AkerSyncRepo\work\akerpuls_full_skane_d0_plan_v1"
set "LOCAL_PATHS=%CD%\config\local_paths.json"
if not "%~1"=="" set "OUT=%~1"
if not "%~2"=="" set "LOCAL_PATHS=%~2"

echo ========================================================================================
echo AkerPuls split fusion QA v1 - FULL SKANE D0 ZERO-PU EXECUTION PLAN
echo ========================================================================================
echo Output:      %OUT%
echo Local paths: %LOCAL_PATHS%
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean.
  git status --short
  exit /b 1
)
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)
for /f "delims=" %%T in ('git rev-list -n 1 %EXPECTED_TAG% 2^>nul') do set "TAG_COMMIT=%%T"
if not defined TAG_COMMIT (
  echo FAIL: local freeze tag %EXPECTED_TAG% missing. Run git fetch --tags.
  exit /b 1
)
if /I not "%TAG_COMMIT%"=="%EXPECTED_FREEZE_COMMIT%" (
  echo FAIL: freeze tag resolves to %TAG_COMMIT%, expected %EXPECTED_FREEZE_COMMIT%.
  exit /b 1
)
where py >nul 2>nul || (echo FAIL: Python launcher py is missing.& exit /b 1)
if not exist "%LOCAL_PATHS%" (echo FAIL: missing %LOCAL_PATHS%& exit /b 1)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_stopa0\preflight_manifest.json" (
  echo FAIL: frozen A0 preflight manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_stopa0\tile_plan.csv" (
  echo FAIL: frozen A0 tile plan missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_stopa0\snapshot_coverage.csv" (
  echo FAIL: frozen A0 snapshot coverage missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_fusion_freeze_c7a_v0\FUSION_SCORE_FREEZE_BEFORE_C7.json" (
  echo FAIL: frozen fusion artifact missing.
  exit /b 1
)
py -3 -c "import numpy,pandas,geopandas,shapely" >nul 2>nul || (
  echo FAIL: required Python dependencies numpy/pandas/geopandas/shapely are missing.
  exit /b 1
)

if not exist "%OUT%\logs" mkdir "%OUT%\logs"

py -3 -m unittest tests.test_akerpuls_full_skane_d0_plan_v1 -v > "%OUT%\logs\tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\tests.log"
if not "%RC%"=="0" goto :fail

echo.
echo D0 planner starts now. Progress is printed live; no Sentinel Hub PU is used.
echo.
py -3 src\138_akerpuls_full_skane_d0_plan_v1.py --local-paths "%LOCAL_PATHS%" --output-dir "%OUT%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :review

for %%F in (
  "%OUT%\d0_raster_tiles.csv"
  "%OUT%\d0_raster_tiles.gpkg"
  "%OUT%\d0_scene_inventory.csv"
  "%OUT%\d0_snapshot_coverage.csv"
  "%OUT%\d0_process_request_plan.csv"
  "%OUT%\d0_snapshot_tile_plan.csv"
  "%OUT%\d0_field_partition.csv"
  "%OUT%\d0_analysis_cells.csv"
  "%OUT%\d0_analysis_cells.gpkg"
  "%OUT%\D1_EXECUTION_CONTRACT.json"
  "%OUT%\d0_manifest.json"
  "%OUT%\d0_qa.md"
) do if not exist "%%~F" (echo FAIL: missing artifact %%~F& goto :fail)

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D0 changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo ========================================================================================
echo STOPPUNKT D0: PASS - NO PROCESS API CALLS, ZERO PU
echo ========================================================================================
echo Return the complete console summary to ChatGPT before D1 is implemented/run.
echo.
exit /b 0

:review
echo.
echo ========================================================================================
echo STOPPUNKT D0: REVIEW REQUIRED - DO NOT START D1
echo ========================================================================================
echo D0 itself used zero PU. Return the console output to ChatGPT.
exit /b %RC%

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D0: FAIL - DO NOT START D1
echo ========================================================================================
echo Return the console output and %OUT%\logs\tests.log to ChatGPT.
exit /b 1
