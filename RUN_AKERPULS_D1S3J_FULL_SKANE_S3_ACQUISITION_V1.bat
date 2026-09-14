@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "WORKOUT=C:\AkerSyncRepo\work\akerpuls_d1s3j_full_skane_s3_acquisition_v1"
set "DERIVED=C:\AkerSyncRaw\akerpuls_full_skane_s3_v1"
if not "%~1"=="" set "WORKOUT=%~1"
if not "%~2"=="" set "DERIVED=%~2"

echo ========================================================================================
echo AkerPuls D1-S3J - FULL-SKANE DIRECT-S3 ACQUISITION - FROZEN INVENTORY / ZERO PROCESS PU
echo ========================================================================================
echo Exact parent contract: 9764672a66938f7526c8cca9ab2140ec205d4ad993f798239b627c17c559bbc8
echo Downloads ONLY missing assets from the frozen D1-S3i S3 catalog.
echo Builds 593 daily tiles, 568 snapshot tiles and 4 VRTs. Resumable by SHA256 sidecars.
echo NO STAC query, NO Process API, NO model run, NO geometry mutation.
echo Work output: %WORKOUT%
echo Derived root: %DERIVED%
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

if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3i_full_skane_s3_plan_v1\d1s3i_manifest.json" (
  echo FAIL: D1-S3i PASS manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3i_full_skane_s3_plan_v1\FULL_SKANE_S3_EXECUTION_CONTRACT.json" (
  echo FAIL: frozen full-Skane S3 execution contract missing.
  exit /b 1
)
py -3 -c "import numpy,pandas,rasterio,boto3,botocore" >nul 2>nul || (
  echo FAIL: required Python dependencies are missing.
  exit /b 1
)

if not exist "%WORKOUT%" mkdir "%WORKOUT%"
if not exist "%DERIVED%" mkdir "%DERIVED%"
py -3 -m unittest tests.test_akerpuls_d1s3j_full_skane_s3_acquisition_v1 -v
if errorlevel 1 goto :fail

echo.
echo D1-S3j starts now. It is safe to interrupt and rerun; verified raw assets and derived tiles are cache-reused.
echo This can take substantial local compute time because 593 tiles are reprojected from original Sentinel-2 assets.
echo.
py -3 -u src\151_akerpuls_d1s3j_full_skane_s3_acquisition_v1.py --work-output-dir "%WORKOUT%" --derived-root "%DERIVED%"
set "RC=%ERRORLEVEL%"

if not exist "%WORKOUT%\d1s3j_manifest.json" (
  echo FAIL: d1s3j_manifest.json missing. A partial run may still be safely resumable.
  goto :fail
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D1-S3j changed Git-visible files.
  git status --short
  goto :fail
)

if "%RC%"=="0" goto :pass
if "%RC%"=="2" goto :review
goto :fail

:pass
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3J: PASS - FULL-SKANE S3 RASTERS BUILT; NEXT STEP IS ZERO-NETWORK D1 QA
echo ========================================================================================
echo No model/fusion run or geometry mutation occurred. Return the summary to ChatGPT.
exit /b 0

:review
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3J: REVIEW - DO NOT START D2 MODEL EXECUTION
echo ========================================================================================
echo Return the summary to ChatGPT. Process PU remains zero.
exit /b 2

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3J: FAIL OR BLOCKED
 echo ========================================================================================
echo No Sentinel Hub Process API calls are made by this stage. Partial derived outputs are resumable.
exit /b 1
