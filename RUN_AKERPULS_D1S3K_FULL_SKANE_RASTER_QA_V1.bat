@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_d1s3k_full_skane_raster_qa_v1"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo AkerPuls D1-S3K - FULL-SKANE ZERO-NETWORK RASTER / FIELD-VALIDITY QA
echo ========================================================================================
echo Reads only completed D1-S3j snapshot rasters and frozen 2025 field geometry.
echo NO STAC, NO S3 objects, NO Process API, NO model/fusion execution, NO geometry mutation.
echo Scans all 142 tiles x 4 snapshots and all 128636 fields.
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

if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3j_full_skane_s3_acquisition_v1\d1s3j_manifest.json" (
  echo FAIL: D1-S3j PASS manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3j_full_skane_s3_acquisition_v1\d1s3j_snapshot_outputs.csv" (
  echo FAIL: D1-S3j snapshot output index missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_full_skane_d0b_sparse_norm_v1\D1_EXECUTION_CONTRACT_FINAL.json" (
  echo FAIL: D0b final execution contract missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_full_skane_d0_plan_v1\d0_field_partition.csv" (
  echo FAIL: D0 field partition missing.
  exit /b 1
)
py -3 -c "import numpy,pandas,rasterio,geopandas,shapely" >nul 2>nul || (
  echo FAIL: required Python dependencies are missing.
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
py -3 -m unittest tests.test_akerpuls_d1s3k_full_skane_raster_qa_v1 -v
if errorlevel 1 goto :fail

echo.
echo D1-S3k starts now. This is local disk/CPU QA only and may take several minutes.
echo.
py -3 -u src\152_akerpuls_d1s3k_full_skane_raster_qa_v1.py --output-dir "%OUT%"
set "RC=%ERRORLEVEL%"

if not exist "%OUT%\d1s3k_manifest.json" (
  echo FAIL: d1s3k_manifest.json missing.
  goto :fail
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D1-S3k changed Git-visible files.
  git status --short
  goto :fail
)

if "%RC%"=="0" goto :pass
if "%RC%"=="2" goto :review
goto :fail

:pass
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3K: PASS - RASTER/FIELD QA COMPLETE; NEXT STEP IS D2 MODEL PLAN ONLY
echo ========================================================================================
echo No network or model execution occurred. Return the summary to ChatGPT before D2.
exit /b 0

:review
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3K: REVIEW - DO NOT START FULL-SKANE D2 MODEL EXECUTION
echo ========================================================================================
echo Return the QA summary to ChatGPT. No network or Process PU was used.
exit /b 2

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3K: FAIL OR BLOCKED
echo ========================================================================================
echo This stage contains no network/download/Process/model execution path.
exit /b 1
