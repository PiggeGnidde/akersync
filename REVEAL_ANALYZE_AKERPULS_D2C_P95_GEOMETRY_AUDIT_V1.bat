@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "D2C=C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1"
set "LABELS=%USERPROFILE%\Downloads\p95_geometry_audit_labels.csv"
if not "%~1"=="" set "LABELS=%~1"
if not "%~2"=="" set "D2C=%~2"

set "VIEWER=%D2C%\d2c_p95_geometry_audit_viewer_v1"
set "FREEZE=%D2C%\d2c_p95_geometry_audit_freeze_v1"
set "OUT=%D2C%\d2c_p95_geometry_audit_reveal_v1"

echo ============================================================
echo AKERPULS D2C - REVEAL + ANALYZE P95 GEOMETRY AUDIT V1
echo EXACT PRE-REVEAL FREEZE + EXACT BLIND KEY
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
  echo ERROR: working tree must be clean before reveal.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)
if not exist "%LABELS%" (
  echo ERROR: frozen geometry-audit labels not found:
  echo %LABELS%
  echo Usage:
  echo   REVEAL_ANALYZE_AKERPULS_D2C_P95_GEOMETRY_AUDIT_V1.bat "C:\path\p95_geometry_audit_labels.csv"
  exit /b 1
)
if not exist "%FREEZE%\P95_GEOMETRY_AUDIT_FREEZE_V1.json" (
  echo ERROR: missing pre-reveal geometry-audit freeze
  exit /b 1
)
if not exist "%VIEWER%\BLIND_KEY_DO_NOT_OPEN_BEFORE_GEOMETRY_REVIEW.csv" (
  echo ERROR: missing frozen blind key
  exit /b 1
)

echo.
echo [1/2] Unit tests
py -3 -m unittest tests.test_akerpuls_d2c_p95_geometry_audit_reveal_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Reveal exact blind key and analyze frozen 100-field audit
py -3 -u src\164_akerpuls_d2c_p95_geometry_audit_reveal_v1.py "%LABELS%" --d2c-dir "%D2C%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\p95_geometry_audit_revealed_100.csv" (echo ERROR: revealed joined CSV not created& exit /b 1)
if not exist "%OUT%\P95_GEOMETRY_AUDIT_REVEAL_SUMMARY_V1.json" (echo ERROR: reveal summary not created& exit /b 1)
if not exist "%OUT%\P95_GEOMETRY_AUDIT_REVEAL_REPORT_V1.md" (echo ERROR: reveal report not created& exit /b 1)
if not exist "%OUT%\p95_geometry_audit_reveal_manifest.json" (echo ERROR: reveal manifest not created& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during reveal.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: frozen P95 geometry audit revealed and analyzed.
echo No model, threshold, fusion, or official geometry was changed.
echo OUTPUT=%OUT%
echo ============================================================
exit /b 0
