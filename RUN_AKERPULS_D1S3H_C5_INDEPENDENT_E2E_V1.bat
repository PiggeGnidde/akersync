@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_d1s3h_c5_independent_e2e_v1"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo AkerPuls D1-S3H - C5 GEOGRAPHIC END-TO-END BACKEND CONFIRMATION - ZERO PROCESS PU
echo ========================================================================================
echo C7 remains REVIEW. This stage uses a NEW acceptance contract frozen before C5 S3 outcomes.
echo Original C5B Process rasters are read-only references; direct S3 rebuilds the same 1000-field grid.
echo The global low-tier fusion max is diagnostic only; P90+ union max and tier stability are acceptance metrics.
echo It NEVER calls Sentinel Hub Process API and never changes geometry.
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

if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3f_c7_end_to_end_parity_v1\d1s3f_manifest.json" (
  echo FAIL: D1-S3f REVIEW manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3g_review_diagnostic_v1\d1s3g_manifest.json" (
  echo FAIL: D1-S3g diagnostic manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c5a_selection\c5a_pilot_fields_2025.gpkg" (
  echo FAIL: C5A pilot geometry missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c5b_rasters\c5b_manifest.json" (
  echo FAIL: C5B Process reference manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c5c_validation\c5c_field_validation.csv" (
  echo FAIL: legacy C5C validation missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_fusion_freeze_c7a_v0\FUSION_SCORE_FREEZE_BEFORE_C7.json" (
  echo FAIL: frozen fusion artifact missing.
  exit /b 1
)
py -3 -c "import numpy,pandas,rasterio,geopandas,scipy,boto3,botocore" >nul 2>nul || (
  echo FAIL: required Python dependencies are missing.
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
py -3 -m unittest tests.test_akerpuls_d1s3h_c5_independent_e2e_v1 -v
if errorlevel 1 goto :fail

echo.
echo D1-S3h starts now. C5 direct-S3 outcomes have not been used to choose this acceptance contract.
echo Public STAC and direct S3 may be used; Sentinel Hub Process API is forbidden.
echo Existing S3 scene assets are cache-reused.
echo.
py -3 -u src\149_akerpuls_d1s3h_c5_independent_e2e_v1.py --output-dir "%OUT%"
set "RC=%ERRORLEVEL%"

if not exist "%OUT%\d1s3h_manifest.json" (
  echo FAIL: d1s3h_manifest.json missing.
  goto :fail
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D1-S3h changed Git-visible files.
  git status --short
  goto :fail
)

if "%RC%"=="0" goto :pass
if "%RC%"=="2" goto :review
goto :fail

:pass
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3H: PASS - C5 CONFIRMED BACKEND; NEXT STEP IS FULL-SKANE S3 PLAN ONLY
echo ========================================================================================
echo C7 remains historically REVIEW. No full-Skane acquisition or geometry mutation occurred here.
exit /b 0

:review
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3H: REVIEW - DO NOT START FULL-SKANE S3 ACQUISITION
echo ========================================================================================
echo Return the comparison summary to ChatGPT. No Process PU was spent.
exit /b 2

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3H: FAIL OR BLOCKED
echo ========================================================================================
echo No Sentinel Hub Process API calls are made by this stage.
exit /b 1
