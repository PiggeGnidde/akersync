@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "SRC=C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_reveal_analysis_v1"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_reveal_analysis_freeze_v1"

echo ============================================================
echo AKERPULS - FORMAL FREEZE OF BLIND MERGE REVEAL ANALYSIS
echo NO FUSION / NO SIGN SELECTION / NO RETUNING
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
  echo ERROR: working tree must be clean before reveal freeze.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if not exist "%SRC%\MERGE_AUDIT_REVEAL_ANALYSIS_SUMMARY_V1.json" (
  echo ERROR: completed reveal analysis missing.
  exit /b 1
)
if exist "%OUT%" (
  echo ERROR: reveal-analysis freeze already exists: %OUT%
  exit /b 1
)

echo.
echo [1/2] Reveal-freeze contract tests
py -3 -m unittest tests.test_akerpuls_merge_reveal_analysis_freeze_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Verify and formally freeze revealed audit analysis
py -3 -u src\196_akerpuls_merge_reveal_analysis_freeze_v1.py --source-dir "%SRC%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\AKERPULS_MERGE_BLIND_AUDIT_REVEAL_ANALYSIS_FREEZE_V1.json" (echo ERROR: freeze JSON missing& exit /b 1)
if not exist "%OUT%\AKERPULS_MERGE_BLIND_AUDIT_REVEAL_ANALYSIS_FREEZE_V1.sha256" (echo ERROR: freeze SHA missing& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during reveal freeze.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: revealed blind-audit analysis formally frozen.
echo No fusion/sign/tuning/geometry mutation occurred.
echo OUTPUT=%OUT%
echo NEXT STOP: decide M1 role from frozen evidence.
echo ============================================================
exit /b 0
