@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_viewer_v1"

echo ============================================================
echo AKERPULS - BLIND 100-PAIR M0/M1 DISAGREEMENT AUDIT VIEWER
echo 25 EACH: HH / HL / LH / LL EXTREME DECILES
echo SCORES + STRATA + PAIR IDs HIDDEN
echo ============================================================
echo OUTPUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before audit-viewer build.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if exist "%OUT%" (
  echo ERROR: audit-viewer output already exists: %OUT%
  echo Preserve prior evidence; do not overwrite.
  exit /b 1
)

echo.
echo [1/2] Blind audit contract tests
py -3 -m unittest tests.test_akerpuls_merge_blind_disagreement_audit_viewer_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Build deterministic 4x25 blind audit viewer
py -3 -u src\190_akerpuls_merge_blind_disagreement_audit_viewer_v1.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\index.html" (echo ERROR: viewer HTML missing& exit /b 1)
if not exist "%OUT%\BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv" (echo ERROR: blind key missing& exit /b 1)
if not exist "%OUT%\MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_MANIFEST_V1.json" (echo ERROR: viewer manifest missing& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during audit-viewer build.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: blind disagreement audit viewer built.
echo DO NOT OPEN BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv.
echo Open:
echo   %OUT%\index.html
echo Complete all 100 labels and export merge_disagreement_audit_labels.csv.
echo Then STOP. Do not inspect/reveal strata yet.
echo ============================================================
exit /b 0
