@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "SRC=C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_viewer_v1b"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_viewer_freeze_v1"

echo ============================================================
echo AKERPULS - FORMAL PRE-LABEL BLIND MERGE AUDIT VIEWER FREEZE
echo VERIFY EXACT 100-PAIR SAMPLE + 100 RENDERS + BLIND KEY HASH
echo DO NOT REVEAL BLIND KEY CONTENTS
echo ============================================================
echo SOURCE=%SRC%
echo OUTPUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before audit-viewer freeze.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if not exist "%SRC%\MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_MANIFEST_V1.json" (
  echo ERROR: completed V1B viewer package missing.
  exit /b 1
)
if exist "%OUT%" (
  echo ERROR: audit-viewer freeze already exists: %OUT%
  echo Do not overwrite a freeze.
  exit /b 1
)

echo.
echo [1/2] Pre-label viewer-freeze contract tests
py -3 -m unittest tests.test_akerpuls_merge_blind_disagreement_audit_viewer_freeze_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Verify and freeze exact blind audit viewer/sample
py -3 -u src\192_akerpuls_merge_blind_disagreement_audit_viewer_freeze_v1.py --source-dir "%SRC%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_FREEZE_V1.json" (
  echo ERROR: audit-viewer freeze JSON missing
  exit /b 1
)
if not exist "%OUT%\AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_FREEZE_V1.sha256" (
  echo ERROR: audit-viewer freeze SHA missing
  exit /b 1
)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during audit-viewer freeze.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: exact pre-label blind audit viewer/sample formally frozen.
echo NOW open the existing V1B index.html and complete all 100 labels.
echo DO NOT open BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv.
echo Export merge_disagreement_audit_labels.csv and STOP.
echo ============================================================
exit /b 0
