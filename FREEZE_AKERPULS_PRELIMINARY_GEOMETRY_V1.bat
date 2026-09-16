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
set "OUT=%D2C%\akerpuls_preliminary_geometry_v1_freeze"

echo ============================================================
echo AKERPULS - PRELIMINARY GEOMETRY V1 FORMAL FREEZE
echo P95 REVIEW-ONLY 2026 SPLIT PROPOSALS
echo ============================================================
echo D2C=%D2C%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before v1 freeze.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)

if not exist "%D2C%\d2c_visual_audit_freeze_v1\D2C_HUMAN_AUDIT_FREEZE_V1.json" (
  echo ERROR: missing first human-audit freeze
  exit /b 1
)
if not exist "%D2C%\d2c_p95_split_line_freeze_v1\P95_SPLIT_LINE_PROPOSAL_FREEZE_V1.json" (
  echo ERROR: missing P95 split-line proposal freeze
  exit /b 1
)
if not exist "%D2C%\d2c_p95_geometry_audit_freeze_v1\P95_GEOMETRY_AUDIT_FREEZE_V1.json" (
  echo ERROR: missing pre-reveal geometry-audit freeze
  exit /b 1
)
if not exist "%D2C%\d2c_p95_geometry_audit_reveal_v1\P95_GEOMETRY_AUDIT_REVEAL_SUMMARY_V1.json" (
  echo ERROR: missing revealed geometry-audit summary
  exit /b 1
)

echo.
echo [1/2] Unit tests
py -3 -m unittest tests.test_akerpuls_preliminary_geometry_v1_freeze -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Freeze ÅkerPuls preliminary geometry v1
py -3 -u src\165_akerpuls_preliminary_geometry_v1_freeze.py --d2c-dir "%D2C%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\AKERPULS_PRELIMINARY_GEOMETRY_V1_FREEZE.json" (echo ERROR: v1 freeze JSON not created& exit /b 1)
if not exist "%OUT%\akerpuls_preliminary_geometry_v1_manifest.json" (echo ERROR: v1 manifest not created& exit /b 1)
if not exist "%OUT%\akerpuls_preliminary_geometry_v1_index.csv" (echo ERROR: 618-field v1 product index not created& exit /b 1)
if not exist "%OUT%\AKERPULS_PRELIMINARY_GEOMETRY_V1_REPORT.md" (echo ERROR: v1 report not created& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during v1 freeze.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: ÅkerPuls preliminary geometry v1 formally frozen.
echo 2025 geometry remains canonical; 2026 geometry is proposal-only.
echo OUTPUT=%OUT%
echo ============================================================
exit /b 0
