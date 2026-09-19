@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "SRC=C:\AkerSyncRepo\work\akerpuls_merge_m1_m4_pair_prior_v1b"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_m1_m4_pair_prior_freeze_v1"

echo ============================================================
echo AKERPULS - FORMAL M1 M4 PAIR PRIOR FREEZE V1
echo VERIFY EXACT 27146-PAIR HISTORY/CONTEXT ARTEFACT
echo NO M0 SATELLITE EVIDENCE / NO FUSION / NO MERGE DECISION
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
  echo ERROR: working tree must be clean before M1 freeze.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if not exist "%SRC%\M1_M4_PAIR_PRIOR_SUMMARY_V1.json" (
  echo ERROR: completed M1 V1B package missing.
  exit /b 1
)
if exist "%OUT%" (
  echo ERROR: M1 freeze output already exists: %OUT%
  echo Do not overwrite a freeze.
  exit /b 1
)

echo.
echo [1/2] M1 freeze contract tests
py -3 -m unittest tests.test_akerpuls_merge_m1_m4_pair_prior_freeze_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Verify and formally freeze independent M1 pair prior
py -3 -u src\187_akerpuls_merge_m1_m4_pair_prior_freeze_v1.py --source-dir "%SRC%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\AKERPULS_MERGE_M1_M4_PAIR_PRIOR_FREEZE_V1.json" (echo ERROR: M1 freeze JSON missing& exit /b 1)
if not exist "%OUT%\AKERPULS_MERGE_M1_M4_PAIR_PRIOR_FREEZE_V1.sha256" (echo ERROR: M1 freeze SHA missing& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during M1 freeze.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: independent M1 M4 pair prior formally frozen.
echo No M0 satellite score/status, fusion, tuning, decision or geometry mutation occurred.
echo OUTPUT=%OUT%
echo NEXT STOP: inspect freeze SHA before any M2 comparison.
echo ============================================================
exit /b 0
