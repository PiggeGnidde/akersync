@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "D2C=C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1"
if not "%~1"=="" set "D2C=%~1"

echo ============================================================
echo AKERPULS D2C - P95 SPLIT-LINE PROPOSAL FREEZE V1
echo EXACT 618-FIELD REVIEW-ONLY GEOMETRY PACKAGE
echo ============================================================
echo D2C=%D2C%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before proposal freeze.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)
if not exist "%D2C%\d2c_p95_split_line_review_v1\p95_split_line_review_manifest.json" (
  echo ERROR: missing P95 split-line review manifest
  exit /b 1
)

echo.
echo [1/2] Unit tests
py -3 -m unittest tests.test_akerpuls_d2c_p95_split_line_freeze_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Freeze exact P95 proposal package
py -3 -u src\161_akerpuls_d2c_p95_split_line_freeze_v1.py --d2c-dir "%D2C%"
if errorlevel 1 exit /b 1

set "OUT=%D2C%\d2c_p95_split_line_freeze_v1"
if not exist "%OUT%\P95_SPLIT_LINE_PROPOSAL_FREEZE_V1.json" (echo ERROR: proposal freeze JSON not created& exit /b 1)
if not exist "%OUT%\p95_split_line_freeze_manifest.json" (echo ERROR: proposal freeze manifest not created& exit /b 1)
if not exist "%OUT%\P95_SPLIT_LINE_PROPOSAL_FREEZE_REPORT_V1.md" (echo ERROR: proposal freeze report not created& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during proposal freeze.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: exact P95 split-line proposal package frozen.
echo NEXT STOP: build blind 100-field geometry audit viewer bound to freeze SHA.
echo OUTPUT=%OUT%
echo ============================================================
exit /b 0
