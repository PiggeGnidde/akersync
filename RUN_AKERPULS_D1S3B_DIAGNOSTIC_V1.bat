@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_d1s3b_diagnostic_v1"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo AkerPuls D1-S3B - POST-REVIEW BACKEND MISMATCH DIAGNOSTIC - ZERO PU
 echo ========================================================================================
echo This stage uses only cached Process references and already downloaded S3 assets.
echo It makes no Process API calls, no S3 downloads, and changes no thresholds/model rules.
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
if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3_parity_v1\d1s3_manifest.json" (
  echo FAIL: parent D1-S3 parity manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRaw\akerpuls_d1s3_parity_v1\items" (
  echo FAIL: D1-S3 S3 cache is missing.
  exit /b 1
)
py -3 -c "import numpy,pandas,rasterio" >nul 2>nul || (
  echo FAIL: required Python dependencies numpy/pandas/rasterio are missing.
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
py -3 -m unittest tests.test_akerpuls_d1s3b_diagnostic_v1 -v
if errorlevel 1 goto :fail

echo.
echo D1-S3b diagnostic starts now. No credentials are needed because no downloads occur.
echo It tests scene-order, coverage-mask and reflectance-harmonization explanations only.
echo.
py -3 -u src\143_akerpuls_d1s3b_diagnostic_v1.py --output-dir "%OUT%"
if errorlevel 1 goto :fail

if not exist "%OUT%\d1s3b_manifest.json" (echo FAIL: d1s3b_manifest.json missing.& goto :fail)
if not exist "%OUT%\d1s3b_variant_metrics.csv" (echo FAIL: d1s3b_variant_metrics.csv missing.& goto :fail)
if not exist "%OUT%\d1s3b_best_by_date.csv" (echo FAIL: d1s3b_best_by_date.csv missing.& goto :fail)

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D1-S3b changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo ========================================================================================
echo STOPPUNKT D1-S3B: DIAGNOSTIC COMPLETE - STILL NO FULL-SKANE S3 AUTHORIZATION
 echo ========================================================================================
echo Return the D1S3B_BEST lines and final summary to ChatGPT.
exit /b 0

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3B: FAIL OR BLOCKED
 echo ========================================================================================
echo No Sentinel Hub Process API calls or S3 downloads are made by this stage.
exit /b 1
