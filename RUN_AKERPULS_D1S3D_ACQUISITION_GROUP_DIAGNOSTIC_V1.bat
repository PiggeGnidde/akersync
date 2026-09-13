@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_d1s3d_acquisition_group_diagnostic_v1"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo AkerPuls D1-S3D - ACQUISITION-GROUP DIAGNOSTIC - ZERO NETWORK / ZERO PU
echo ========================================================================================
echo Uses only completed D1-S3c holdout artifacts and already cached S3 assets.
echo It makes no STAC queries, no S3 downloads and no Sentinel Hub Process API calls.
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
if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3c_independent_holdout_v1\d1s3c_manifest.json" (
  echo FAIL: completed D1-S3c manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3c_independent_holdout_v1\stac_scene_cache" (
  echo FAIL: D1-S3c normalized STAC cache missing.
  exit /b 1
)
if not exist "C:\AkerSyncRaw\akerpuls_d1s3_parity_v1\items" (
  echo FAIL: direct-S3 asset cache missing.
  exit /b 1
)
py -3 -c "import numpy,pandas,rasterio" >nul 2>nul || (
  echo FAIL: required Python dependencies numpy/pandas/rasterio are missing.
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
py -3 -m unittest tests.test_akerpuls_d1s3d_acquisition_group_diagnostic_v1 -v
if errorlevel 1 goto :fail

echo.
echo D1-S3d starts now. This is post-holdout diagnosis only; no rule is authorized here.
echo.
py -3 -u src\145_akerpuls_d1s3d_acquisition_group_diagnostic_v1.py --output-dir "%OUT%"
if errorlevel 1 goto :fail

if not exist "%OUT%\d1s3d_manifest.json" (echo FAIL: d1s3d_manifest.json missing.& goto :fail)
if not exist "%OUT%\d1s3d_variant_metrics.csv" (echo FAIL: d1s3d_variant_metrics.csv missing.& goto :fail)
if not exist "%OUT%\d1s3d_best_by_request.csv" (echo FAIL: d1s3d_best_by_request.csv missing.& goto :fail)

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D1-S3d changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo ========================================================================================
echo STOPPUNKT D1-S3D: DIAGNOSTIC COMPLETE - NO FULL-SKANE S3 AUTHORIZATION
 echo ========================================================================================
echo Return D1S3D_GROUPS, D1S3D_BEST and final summary to ChatGPT.
exit /b 0

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3D: FAIL OR BLOCKED
 echo ========================================================================================
echo This stage makes no network calls and spends zero Sentinel Hub PU.
exit /b 1
