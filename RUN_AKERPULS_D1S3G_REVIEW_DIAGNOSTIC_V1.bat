@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_d1s3g_review_diagnostic_v1"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo AkerPuls D1-S3G - POST-REVIEW DIAGNOSTIC - ZERO NETWORK / ZERO PU
echo ========================================================================================
echo Reads only existing D1-S3f/C7 outputs.
echo It does NOT change or reinterpret the frozen D1-S3f acceptance contract.
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
py -3 -c "import numpy,pandas" >nul 2>nul || (echo FAIL: numpy/pandas missing.& exit /b 1)
if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3f_c7_end_to_end_parity_v1\d1s3f_manifest.json" (
  echo FAIL: D1-S3f manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c7c_fusion_validation\c7c_fusion_candidates.csv" (
  echo FAIL: reference C7C fusion candidates missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3f_c7_end_to_end_parity_v1\s3_c7c_fusion_validation\c7c_fusion_candidates.csv" (
  echo FAIL: S3 C7C fusion candidates missing.
  exit /b 1
)

py -3 -m unittest tests.test_akerpuls_d1s3g_review_diagnostic_v1 -v
if errorlevel 1 goto :fail

if not exist "%OUT%" mkdir "%OUT%"
echo.
echo D1-S3g starts now. No credentials, STAC, S3 or Process API are used.
echo.
py -3 -u src\148_akerpuls_d1s3g_review_diagnostic_v1.py --output-dir "%OUT%"
if errorlevel 1 goto :fail

if not exist "%OUT%\d1s3g_manifest.json" (
  echo FAIL: d1s3g_manifest.json missing.
  goto :fail
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D1-S3g changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo ========================================================================================
echo STOPPUNKT D1-S3G: DIAGNOSTIC COMPLETE - D1-S3F REMAINS REVIEW
echo ========================================================================================
echo Return the MAX_FUSION_DIFF_FIELD and MAX_FIELD_SIGNAL lines to ChatGPT.
exit /b 0

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D1-S3G: FAIL OR BLOCKED
echo ========================================================================================
echo No network or PU was used by this stage.
exit /b 1
