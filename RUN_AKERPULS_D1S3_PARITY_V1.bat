@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_d1s3_parity_v1"
set "S3CACHE=C:\AkerSyncRaw\akerpuls_d1s3_parity_v1"
if not "%~1"=="" set "OUT=%~1"
if not "%~2"=="" set "S3CACHE=%~2"

echo ========================================================================================
echo AkerPuls D1-S3 - PROCESS CACHE VS DIRECT CDSE S3 PARITY - ZERO PU
echo ========================================================================================
echo This stage NEVER calls Sentinel Hub Process API and uses 0 PU.
echo It compares cached FLOAT32 Process tiles against original Sentinel-2 L2A assets.
echo Existing Process cache is read-only and preserved.
echo Output:   %OUT%
echo S3 cache: %S3CACHE%
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
if not exist "C:\AkerSyncRepo\work\akerpuls_full_skane_d0b_sparse_norm_v1\D1_EXECUTION_CONTRACT_FINAL.json" (
  echo FAIL: final D0b execution contract missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_full_skane_d0_plan_v1\d0_process_request_plan.csv" (
  echo FAIL: D0 request plan missing.
  exit /b 1
)
py -3 -c "import numpy,pandas,rasterio,boto3,botocore" >nul 2>nul || (
  echo FAIL: required Python dependencies numpy/pandas/rasterio/boto3/botocore are missing.
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"

py -3 -m unittest tests.test_akerpuls_d1s3_parity_v1 -v
if errorlevel 1 goto :fail

echo.
echo D1-S3 parity starts now.
echo It will select cached Process reference tiles, query public STAC, then download only needed S3 assets.
echo No Process API request is permitted by this runner or script.
echo.
py -3 -u src\142_akerpuls_d1s3_parity_v1.py --output-dir "%OUT%" --s3-cache-root "%S3CACHE%"
set "RC=%ERRORLEVEL%"

if not exist "%OUT%\d1s3_manifest.json" (
  echo FAIL: d1s3_manifest.json missing.
  goto :fail
)

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D1-S3 changed Git-visible files.
  git status --short
  goto :fail
)

if "%RC%"=="0" goto :pass
if "%RC%"=="2" goto :review
goto :fail

:pass
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3: PASS - DIRECT S3 BACKEND PARITY CANDIDATE
 echo ========================================================================================
echo Return the final console summary to ChatGPT before any full-Skane S3 run is implemented.
exit /b 0

:review
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3: REVIEW - DO NOT START FULL-SKANE S3 ACQUISITION
 echo ========================================================================================
echo No PU was spent. Return the console summary and parity CSV diagnostics to ChatGPT.
exit /b 2

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3: FAIL OR BLOCKED
 echo ========================================================================================
echo No Sentinel Hub Process API calls are made by this stage.
exit /b 1
