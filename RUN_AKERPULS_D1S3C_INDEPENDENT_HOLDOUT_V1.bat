@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_d1s3c_independent_holdout_v1"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo AkerPuls D1-S3C - INDEPENDENT DIRECT-S3 BACKEND HOLDOUT - ZERO PROCESS PU
echo ========================================================================================
echo Uses cached Process references on new tile/date holdout requests.
echo May download additional original Sentinel-2 assets from CDSE S3.
echo It NEVER calls Sentinel Hub Process API and cannot authorize full-Skane S3 by itself.
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
if "%AWS_ACCESS_KEY_ID%"=="" (echo BLOCKED_S3_CREDENTIALS: AWS_ACCESS_KEY_ID is not set.& exit /b 1)
if "%AWS_SECRET_ACCESS_KEY%"=="" (echo BLOCKED_S3_CREDENTIALS: AWS_SECRET_ACCESS_KEY is not set.& exit /b 1)
if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3b_diagnostic_v1\d1s3b_manifest.json" (
  echo FAIL: D1-S3b diagnostic manifest missing.
  exit /b 1
)
py -3 -c "import numpy,pandas,rasterio,boto3,botocore" >nul 2>nul || (
  echo FAIL: required Python dependencies numpy/pandas/rasterio/boto3/botocore are missing.
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
py -3 -m unittest tests.test_akerpuls_d1s3c_independent_holdout_v1 -v
if errorlevel 1 goto :fail

echo.
echo D1-S3c independent holdout starts now.
echo Candidate backend semantics are already frozen; no variant search/tuning occurs here.
echo Additional S3 scene assets are cached and reusable. Sentinel Hub PU remains zero.
echo.
py -3 -u src\144_akerpuls_d1s3c_independent_holdout_v1.py --output-dir "%OUT%"
if errorlevel 1 goto :fail

if not exist "%OUT%\d1s3c_manifest.json" (echo FAIL: d1s3c_manifest.json missing.& goto :fail)
if not exist "%OUT%\d1s3c_holdout_parity.csv" (echo FAIL: d1s3c_holdout_parity.csv missing.& goto :fail)

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D1-S3c changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo ========================================================================================
echo STOPPUNKT D1-S3C: INDEPENDENT HOLDOUT COMPLETE - NO FULL-SKANE AUTHORIZATION YET
 echo ========================================================================================
echo Return D1S3C_PARITY lines and final summary to ChatGPT.
exit /b 0

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3C: FAIL OR BLOCKED
 echo ========================================================================================
echo No Sentinel Hub Process API calls are made by this stage.
exit /b 1
