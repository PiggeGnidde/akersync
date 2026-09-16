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

set "OUT=%D2C%\d2c_p95_geometry_audit_viewer_v1"

echo ============================================================
echo AKERPULS D2C - BLIND P95 LINE-GEOMETRY AUDIT VIEWER V1
echo 100 / 613 FROZEN LINE-AVAILABLE FIELDS
echo ============================================================
echo D2C=%D2C%
echo D1=%D1%
echo DERIVED=%DERIVED%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before viewer build.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)
if not exist "%D2C%\d2c_p95_split_line_freeze_v1\P95_SPLIT_LINE_PROPOSAL_FREEZE_V1.json" (
  echo ERROR: missing frozen P95 split-line proposal package
  exit /b 1
)
if not exist "%D1%\d1s3j_manifest.json" (echo ERROR: missing D1-S3j manifest& exit /b 1)


echo.
echo [1/2] Unit tests
py -3 -m unittest tests.test_akerpuls_d2c_p95_geometry_audit_viewer_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Build blind 100-field P95 geometry audit viewer
py -3 -u src\162_akerpuls_d2c_p95_geometry_audit_viewer_v1.py --d2c-dir "%D2C%" --d1-dir "%D1%" --derived-root "%DERIVED%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\index.html" (echo ERROR: viewer HTML not created& exit /b 1)
if not exist "%OUT%\p95_geometry_audit_viewer_manifest.json" (echo ERROR: viewer manifest not created& exit /b 1)
if not exist "%OUT%\BLIND_KEY_DO_NOT_OPEN_BEFORE_GEOMETRY_REVIEW.csv" (echo ERROR: blind key not created& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during viewer build.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: blind P95 geometry audit viewer built.
echo DO NOT OPEN: %OUT%\BLIND_KEY_DO_NOT_OPEN_BEFORE_GEOMETRY_REVIEW.csv
echo OPEN: %OUT%\index.html
echo When all 100 have both labels, export p95_geometry_audit_labels.csv.
echo ============================================================
exit /b 0
