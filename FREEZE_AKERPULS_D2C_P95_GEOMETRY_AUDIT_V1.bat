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

set "OUT=%D2C%\d2c_p95_geometry_audit_freeze_v1"

echo ============================================================
echo AKERPULS D2C - P95 GEOMETRY AUDIT FREEZE V1
echo EXACT 100-FIELD BLIND DOUBLE-LABEL EXPORT, NO REVEAL
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
  echo ERROR: working tree must be clean before geometry-audit freeze.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)
if not exist "%LABELS%" (
  echo ERROR: geometry audit labels file not found:
  echo %LABELS%
  echo Usage:
  echo   FREEZE_AKERPULS_D2C_P95_GEOMETRY_AUDIT_V1.bat "C:\path\p95_geometry_audit_labels.csv"
  exit /b 1
)
if not exist "%D2C%\d2c_p95_geometry_audit_viewer_v1\p95_geometry_audit_viewer_manifest.json" (
  echo ERROR: missing geometry audit viewer manifest
  exit /b 1
)

echo.
echo [1/2] Unit tests
py -3 -m unittest tests.test_akerpuls_d2c_p95_geometry_audit_freeze_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Freeze exact blind geometry audit export without reveal
py -3 -u src\163_akerpuls_d2c_p95_geometry_audit_freeze_v1.py "%LABELS%" --d2c-dir "%D2C%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\P95_GEOMETRY_AUDIT_FREEZE_V1.json" (echo ERROR: geometry audit freeze JSON not created& exit /b 1)
if not exist "%OUT%\p95_geometry_audit_freeze_manifest.json" (echo ERROR: geometry audit freeze manifest not created& exit /b 1)
if not exist "%OUT%\P95_GEOMETRY_AUDIT_FREEZE_REPORT_V1.md" (echo ERROR: geometry audit freeze report not created& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during geometry-audit freeze.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: exact blind P95 geometry audit frozen before reveal.
echo NEXT STOP: reveal blind key and analyze frozen audit.
echo OUTPUT=%OUT%
echo ============================================================
exit /b 0
