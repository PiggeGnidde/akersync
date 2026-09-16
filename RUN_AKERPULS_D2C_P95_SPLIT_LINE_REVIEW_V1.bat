@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "D2C=C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1"
set "D2A=C:\AkerSyncRepo\work\akerpuls_d2a_full_skane_split_discovery_v1"
if not "%~1"=="" set "D2C=%~1"
if not "%~2"=="" set "D2A=%~2"
set "OUT=%D2C%\d2c_p95_split_line_review_v1"

echo ============================================================
echo AKERPULS D2C - P95 REVIEW-ONLY SPLIT-LINE PROPOSALS V1
echo EXACT FROZEN D2A/B2 RECONSTRUCTION - NO GEOMETRY ADOPTION
echo ============================================================
echo D2C=%D2C%
echo D2A=%D2A%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before P95 review geometry build.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)
if not exist "%D2C%\d2c_manifest.json" (echo ERROR: missing D2C manifest& exit /b 1)
if not exist "%D2C%\D2C_FULL_SKANE_QA_RANKING_FREEZE_V1.json" (echo ERROR: missing D2C freeze& exit /b 1)
if not exist "%D2C%\d2c_review_p95_2025_geometry.gpkg" (echo ERROR: missing frozen P95 GPKG& exit /b 1)
if not exist "%D2C%\d2c_visual_audit_freeze_v1\D2C_HUMAN_AUDIT_FREEZE_V1.json" (echo ERROR: missing formal human audit freeze& exit /b 1)
if not exist "%D2A%\d2a_manifest.json" (echo ERROR: missing D2A manifest& exit /b 1)
if not exist "%D2A%\d2a_field_split_discovery.csv" (echo ERROR: missing frozen D2A field discovery& exit /b 1)
if exist "%OUT%" (
  echo ERROR: output directory already exists; refusing to overwrite:
  echo %OUT%
  exit /b 1
)

echo.
echo [1/2] Unit tests
py -3 -m unittest tests.test_akerpuls_d2c_p95_split_line_review_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Reconstruct exact D2A/B2 P95 evidence and derive review-only raw interfaces
py -3 -u src\160_akerpuls_d2c_p95_split_line_review_v1.py --d2c-dir "%D2C%" --d2a-dir "%D2A%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\p95_split_line_review_manifest.json" (echo ERROR: P95 review manifest not created& exit /b 1)
if not exist "%OUT%\p95_split_proposal_summary.csv" (echo ERROR: P95 proposal summary not created& exit /b 1)
if not exist "%OUT%\p95_b2_child_evidence_review.gpkg" (echo ERROR: child evidence GPKG not created& exit /b 1)
if not exist "%OUT%\p95_official_2025_parents_review.gpkg" (echo ERROR: parent review GPKG not created& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during review-only geometry build.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: P95 review-only geometry package created.
echo No official 2025 geometry was replaced.
echo OUTPUT=%OUT%
echo Paste the full terminal output into ChatGPT before visual review.
echo ============================================================
exit /b 0
