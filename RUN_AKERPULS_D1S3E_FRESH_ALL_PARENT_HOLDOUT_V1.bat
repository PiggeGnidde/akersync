@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_d1s3e_fresh_all_parent_holdout_v1"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo AkerPuls D1-S3E - FRESH ALL_PARENT DIRECT-S3 HOLDOUT - ZERO PROCESS PU
echo ========================================================================================
echo Excludes every tile ID used by prior D1-S3/D1-S3c validation.
echo Frozen backend: ALL acquisitions, PARENT order, SCL_NONZERO, SCALE_OFFSET, NEAREST.
echo PASS permits only a later end-to-end model-pipeline parity test.
echo It NEVER calls Sentinel Hub Process API.
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
if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3d_acquisition_group_diagnostic_v1\d1s3d_manifest.json" (
  echo FAIL: D1-S3d diagnostic manifest missing.
  exit /b 1
)
py -3 -c "import numpy,pandas,rasterio,boto3,botocore" >nul 2>nul || (
  echo FAIL: required Python dependencies numpy/pandas/rasterio/boto3/botocore are missing.
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
py -3 -m unittest tests.test_akerpuls_d1s3e_fresh_all_parent_holdout_v1 -v
if errorlevel 1 goto :fail

echo.
echo D1-S3e starts now. Acceptance criteria and ALL_PARENT semantics are already frozen.
echo Public STAC may be queried with retry/backoff; S3 assets are cached and reusable.
echo Sentinel Hub Process PU remains zero.
echo.
py -3 -u src\146_akerpuls_d1s3e_fresh_all_parent_holdout_v1.py --output-dir "%OUT%"
set "RC=%ERRORLEVEL%"

if not exist "%OUT%\d1s3e_manifest.json" (echo FAIL: d1s3e_manifest.json missing.& goto :fail)
if not exist "%OUT%\d1s3e_holdout_parity.csv" (echo FAIL: d1s3e_holdout_parity.csv missing.& goto :fail)
if not exist "%OUT%\d1s3e_selected_holdout_requests.csv" (echo FAIL: selected holdout CSV missing.& goto :fail)

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D1-S3e changed Git-visible files.
  git status --short
  goto :fail
)

if "%RC%"=="0" goto :pass
if "%RC%"=="2" goto :review
goto :fail

:pass
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3E: PASS - PROCEED ONLY TO END-TO-END PIPELINE PARITY
 echo ========================================================================================
echo Full-Skane S3 is still NOT authorized. Return the console summary to ChatGPT.
exit /b 0

:review
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3E: REVIEW - DO NOT RETUNE ON THIS HOLDOUT
 echo ========================================================================================
echo Full-Skane S3 remains unauthorized. Return parity and acceptance lines to ChatGPT.
exit /b 2

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3E: FAIL OR BLOCKED
 echo ========================================================================================
echo No Sentinel Hub Process API calls are made by this stage.
exit /b 1
