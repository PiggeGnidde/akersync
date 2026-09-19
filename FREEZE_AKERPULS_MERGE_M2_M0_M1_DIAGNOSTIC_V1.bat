@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "SRC=C:\AkerSyncRepo\work\akerpuls_merge_m2_m0_m1_diagnostic_v1"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_m2_m0_m1_diagnostic_freeze_v1"

echo ============================================================
echo AKERPULS - FORMAL M2 M0-vs-M1 DIAGNOSTIC FREEZE V1
echo VERIFY DESCRIPTIVE COMPARISON ONLY
echo NO FUSION / NO SIGN / NO HUMAN LABEL / NO RETUNING
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
  echo ERROR: working tree must be clean before M2 freeze.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if not exist "%SRC%\M2_M0_M1_DIAGNOSTIC_SUMMARY_V1.json" (
  echo ERROR: completed M2 diagnostic package missing.
  exit /b 1
)
if exist "%OUT%" (
  echo ERROR: M2 freeze output already exists: %OUT%
  echo Do not overwrite a freeze.
  exit /b 1
)

echo.
echo [1/2] M2 freeze contract tests
py -3 -m unittest tests.test_akerpuls_merge_m2_m0_m1_diagnostic_freeze_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Verify and formally freeze M2 diagnostic
py -3 -u src\189_akerpuls_merge_m2_m0_m1_diagnostic_freeze_v1.py --source-dir "%SRC%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\AKERPULS_MERGE_M2_M0_M1_DIAGNOSTIC_FREEZE_V1.json" (echo ERROR: M2 freeze JSON missing& exit /b 1)
if not exist "%OUT%\AKERPULS_MERGE_M2_M0_M1_DIAGNOSTIC_FREEZE_V1.sha256" (echo ERROR: M2 freeze SHA missing& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during M2 freeze.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: M2 M0-vs-M1 diagnostic formally frozen.
echo No fusion, sign selection, human-label analysis, tuning or geometry mutation occurred.
echo OUTPUT=%OUT%
echo NEXT STOP: inspect freeze SHA before building blind disagreement audit.
echo ============================================================
exit /b 0
