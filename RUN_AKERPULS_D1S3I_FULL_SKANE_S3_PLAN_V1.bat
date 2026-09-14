@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_d1s3i_full_skane_s3_plan_v1"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo AkerPuls D1-S3I - FULL-SKANE DIRECT-S3 PLAN ONLY - PUBLIC STAC / ZERO DOWNLOAD / ZERO PU
echo ========================================================================================
echo Prerequisite: D1-S3h PASS. Historical C7 remains REVIEW.
echo This stage freezes exact scene IDs, assets and tile-scene mapping for the 593 D0 daily rows.
echo It makes public STAC queries only: NO S3 object calls, NO S3 downloads, NO Process API, NO model run.
echo AWS credentials are NOT required.
echo Output: %OUT%
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
where py >nul 2>nul || (echo FAIL: Python launcher py is missing.& exit /b 1)

if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3h_c5_independent_e2e_v1\d1s3h_manifest.json" (
  echo FAIL: D1-S3h PASS manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_full_skane_d0b_sparse_norm_v1\D1_EXECUTION_CONTRACT_FINAL.json" (
  echo FAIL: D0b final execution contract missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_full_skane_d0_plan_v1\d0_process_request_plan.csv" (
  echo FAIL: D0 request plan missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_full_skane_d0_plan_v1\d0_raster_tiles.csv" (
  echo FAIL: D0 raster tile plan missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_full_skane_d0_plan_v1\d0_snapshot_tile_plan.csv" (
  echo FAIL: D0 snapshot tile plan missing.
  exit /b 1
)
py -3 -c "import numpy,pandas,rasterio,geopandas,shapely" >nul 2>nul || (
  echo FAIL: required Python dependencies are missing.
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
py -3 -m unittest tests.test_akerpuls_d1s3i_full_skane_s3_plan_v1 tests.test_akerpuls_d1s3i_orderfix_v1 -v
if errorlevel 1 goto :fail

echo.
echo D1-S3i starts now. Public CDSE STAC only. Successful date queries are cached for safe retry.
echo Do not interrupt unless necessary; if a public STAC rate limit occurs, the runner can be rerun.
echo.
py -3 -u src\150b_akerpuls_d1s3i_full_skane_s3_plan_orderfix_v1.py --output-dir "%OUT%"
set "RC=%ERRORLEVEL%"

if not exist "%OUT%\d1s3i_manifest.json" (
  echo FAIL: d1s3i_manifest.json missing.
  goto :fail
)
if not exist "%OUT%\FULL_SKANE_S3_EXECUTION_CONTRACT.json" (
  echo FAIL: FULL_SKANE_S3_EXECUTION_CONTRACT.json missing.
  goto :fail
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D1-S3i changed Git-visible files.
  git status --short
  goto :fail
)

if "%RC%"=="0" goto :pass
if "%RC%"=="2" goto :review
goto :fail

:pass
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3I: PASS - EXACT FULL-SKANE S3 ACQUISITION CONTRACT FROZEN
echo ========================================================================================
echo No S3 object was downloaded and no Process PU was spent. Do NOT run acquisition until reviewed.
exit /b 0

:review
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3I: REVIEW - DO NOT START FULL-SKANE S3 ACQUISITION
echo ========================================================================================
echo Return the D1-S3i summary to ChatGPT. No S3 object download or Process PU occurred.
exit /b 2

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3I: FAIL OR BLOCKED
echo ========================================================================================
echo This stage contains no S3-object download path and no Sentinel Hub Process path.
exit /b 1
