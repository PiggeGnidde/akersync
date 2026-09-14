@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_d1s3f_c7_end_to_end_parity_v1"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo AkerPuls D1-S3F - C7 END-TO-END PROCESS VS DIRECT-S3 PIPELINE PARITY - ZERO PROCESS PU
echo ========================================================================================
echo Rebuilds the exact 1000-field C7 raster grid from direct CDSE S3 using frozen ALL_PARENT.
echo Then reruns frozen C7 split discovery, TRUE-LOO and 3-signal fusion and compares to Process C7.
echo It NEVER calls Sentinel Hub Process API and does not change model or geometry rules.
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
if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3e_fresh_all_parent_holdout_v1\d1s3e_manifest.json" (
  echo FAIL: D1-S3e PASS manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c7b_rasters\c7b_manifest.json" (
  echo FAIL: reference C7B manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c7c_fusion_validation\c7c_summary.json" (
  echo FAIL: reference C7C summary missing.
  exit /b 1
)
py -3 -c "import numpy,pandas,rasterio,geopandas,scipy,boto3,botocore" >nul 2>nul || (
  echo FAIL: required Python dependencies are missing.
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
py -3 -m unittest tests.test_akerpuls_d1s3f_c7_end_to_end_parity_v1 -v
if errorlevel 1 goto :fail

echo.
echo D1-S3f starts now. Acceptance contract and ALL_PARENT backend are already frozen.
echo Public STAC and direct S3 may be used; Sentinel Hub Process API is forbidden.
echo Existing S3 assets are cache-reused.
echo.
py -3 -u src\147_akerpuls_d1s3f_c7_end_to_end_parity_v1.py --output-dir "%OUT%"
set "RC=%ERRORLEVEL%"

if not exist "%OUT%\d1s3f_manifest.json" (
  echo FAIL: d1s3f_manifest.json missing.
  goto :fail
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D1-S3f changed Git-visible files.
  git status --short
  goto :fail
)

if "%RC%"=="0" goto :pass
if "%RC%"=="2" goto :review
goto :fail

:pass
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3F: PASS - END-TO-END PARITY PASSED; NEXT STEP IS FULL-SKANE S3 PLAN ONLY
echo ========================================================================================
echo No full-Skane S3 acquisition was executed by this stage.
exit /b 0

:review
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3F: REVIEW - DO NOT START FULL-SKANE S3 ACQUISITION
echo ========================================================================================
echo Return the comparison summary to ChatGPT. No Process PU was spent.
exit /b 2

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3F: FAIL OR BLOCKED
echo ========================================================================================
echo No Sentinel Hub Process API calls are made by this stage.
exit /b 1
