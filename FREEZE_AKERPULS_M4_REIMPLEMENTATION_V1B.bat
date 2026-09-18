@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "SRC=C:\AkerSyncRepo\work\akerpuls_m4_reproduction_gate_v1b"
set "OUT=C:\AkerSyncRepo\work\akerpuls_m4_reimplementation_v1b_freeze"

echo ============================================================
echo AKERPULS - FORMAL M4 REIMPLEMENTATION V1B FREEZE
echo VERIFY PERSISTENT REPRODUCTION PACKAGE; NO MODEL FIT / 2026
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
  echo ERROR: working tree must be clean before M4 V1B freeze.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if not exist "%SRC%\REPRODUCTION_SUMMARY.json" (
  echo ERROR: completed V1B reproduction package not found.
  exit /b 1
)
if exist "%OUT%" (
  echo ERROR: freeze output already exists: %OUT%
  echo Do not overwrite a freeze.
  exit /b 1
)

echo.
echo [1/2] Freeze contract tests
py -3 -m unittest tests.test_akerpuls_m4_reimplementation_v1b_freeze -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Verify and freeze exact V1B reproduction package
py -3 -u src\182_akerpuls_m4_reimplementation_v1b_freeze.py --source-dir "%SRC%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\AKERPULS_M4_REIMPLEMENTATION_V1B_FREEZE.json" (
  echo ERROR: freeze JSON missing
  exit /b 1
)
if not exist "%OUT%\AKERPULS_M4_REIMPLEMENTATION_V1B_FREEZE.sha256" (
  echo ERROR: freeze SHA file missing
  exit /b 1
)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during freeze.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: M4 V1B reimplementation formally frozen.
echo No model fit or 2026 prediction occurred in freeze.
echo OUTPUT=%OUT%
echo NEXT STOP: inspect freeze SHA before final 2026 prior training.
echo ============================================================
exit /b 0
