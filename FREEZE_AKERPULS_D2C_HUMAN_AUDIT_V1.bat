@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "D2C=C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1"
set "LABELS=%USERPROFILE%\Downloads\d2c_visual_audit_labels.csv"
if not "%~1"=="" set "LABELS=%~1"
if not "%~2"=="" set "D2C=%~2"

echo ============================================================
echo AKERPULS D2C - HUMAN AUDIT FREEZE V1
echo EXACT LABEL EXPORT + REVEALED BLIND KEY
echo ============================================================
echo LABELS=%LABELS%
echo D2C=%D2C%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before audit freeze.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)
if not exist "%LABELS%" (
  echo ERROR: audit labels file not found:
  echo %LABELS%
  echo Usage:
  echo   FREEZE_AKERPULS_D2C_HUMAN_AUDIT_V1.bat "C:\path\d2c_visual_audit_labels.csv"
  exit /b 1
)
if not exist "%D2C%\d2c_manifest.json" (echo ERROR: missing D2C manifest& exit /b 1)
if not exist "%D2C%\D2C_FULL_SKANE_QA_RANKING_FREEZE_V1.json" (echo ERROR: missing D2C freeze& exit /b 1)
if not exist "%D2C%\d2c_visual_audit_viewer_v1\BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv" (
  echo ERROR: missing revealed blind key
  exit /b 1
)

echo.
echo [1/2] Unit tests
py -3 -m unittest tests.test_akerpuls_d2c_human_audit_freeze_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Freeze exact human audit result
py -3 -u src\159_akerpuls_d2c_human_audit_freeze_v1.py "%LABELS%" --d2c-dir "%D2C%"
if errorlevel 1 exit /b 1

set "OUT=%D2C%\d2c_visual_audit_freeze_v1"
if not exist "%OUT%\D2C_HUMAN_AUDIT_FREEZE_V1.json" (echo ERROR: audit freeze JSON not created& exit /b 1)
if not exist "%OUT%\d2c_human_audit_manifest.json" (echo ERROR: audit freeze manifest not created& exit /b 1)
if not exist "%OUT%\D2C_HUMAN_AUDIT_REPORT_V1.md" (echo ERROR: audit report not created& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during freeze.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: formal D2C human audit freeze created.
echo NEXT STOP: P95 review-only split-line proposals.
echo OUTPUT=%OUT%
echo ============================================================
exit /b 0
