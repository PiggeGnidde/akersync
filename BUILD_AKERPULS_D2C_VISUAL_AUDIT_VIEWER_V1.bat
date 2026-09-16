@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "D2C=C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1"
set "D1=C:\AkerSyncRepo\work\akerpuls_d1s3j_full_skane_s3_acquisition_v1"
set "DERIVED=C:\AkerSyncRaw\akerpuls_full_skane_s3_v1"
if not "%~1"=="" set "D2C=%~1"
if not "%~2"=="" set "D1=%~2"
if not "%~3"=="" set "DERIVED=%~3"

echo ============================================================
echo AKERPULS D2C - BLIND 100-FIELD VISUAL AUDIT VIEWER V1
echo POST-FREEZE / ZERO-NETWORK / REVIEW ONLY
echo ============================================================

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before audit build.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)

if not exist "%D2C%\d2c_manifest.json" (echo ERROR: missing %D2C%\d2c_manifest.json& exit /b 1)
if not exist "%D2C%\D2C_FULL_SKANE_QA_RANKING_FREEZE_V1.json" (echo ERROR: missing D2C freeze file& exit /b 1)
if not exist "%D2C%\d2c_visual_audit_sample_100.gpkg" (echo ERROR: missing frozen 100-field audit GPKG& exit /b 1)
if not exist "%D1%\d1s3j_manifest.json" (echo ERROR: missing %D1%\d1s3j_manifest.json& exit /b 1)
if not exist "%D1%\d1s3j_snapshot_outputs.csv" (echo ERROR: missing D1 snapshot index& exit /b 1)
if not exist "%D1%\d1s3j_vrt_outputs.csv" (echo ERROR: missing D1 VRT index& exit /b 1)

echo.
echo [1/2] Unit tests
py -3 -m unittest tests.test_akerpuls_d2c_visual_audit_viewer_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Build blind viewer from frozen D2C sample + frozen D1 VRTs
py -3 -u src\158_akerpuls_d2c_visual_audit_viewer_v1.py --d2c-dir "%D2C%" --d1-dir "%D1%" --derived-root "%DERIVED%"
if errorlevel 1 exit /b 1

set "OUT=%D2C%\d2c_visual_audit_viewer_v1"
if not exist "%OUT%\index.html" (echo ERROR: viewer HTML not created& exit /b 1)
if not exist "%OUT%\d2c_visual_audit_viewer_manifest.json" (echo ERROR: viewer manifest not created& exit /b 1)
if not exist "%OUT%\BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv" (echo ERROR: blind key not created& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during review-only build.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: viewer built; D2C freeze untouched.
echo DO NOT OPEN: %OUT%\BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv
echo OPEN:        %OUT%\index.html
echo When all 100 are labelled, use the viewer button to export:
echo              d2c_visual_audit_labels.csv
echo ============================================================
exit /b 0
