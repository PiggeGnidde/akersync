@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "SRC=C:\AkerSyncRepo\work\akerpuls_m4_2026_prior_v1"
set "OUT=C:\AkerSyncRepo\work\akerpuls_m4_2026_prior_freeze_v1"

echo ============================================================
echo AKERPULS - FORMAL M4 2026 PRIOR FREEZE V1
echo VERIFY BLIND PRIOR + HASHES; NO MODEL FIT / PREDICTION
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
  echo ERROR: working tree must be clean before M4 2026-prior freeze.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if not exist "%SRC%\M4_2026_PRIOR_METADATA.json" (
  echo ERROR: reviewed M4 2026 prior package missing.
  exit /b 1
)
if exist "%OUT%" (
  echo ERROR: freeze output already exists: %OUT%
  echo Do not overwrite a freeze.
  exit /b 1
)

echo.
echo [1/2] Freeze contract tests
py -3 -m unittest tests.test_akerpuls_m4_2026_prior_freeze_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Verify and formally freeze M4 2026 prior
py -3 -u src\184_akerpuls_m4_2026_prior_freeze_v1.py --source-dir "%SRC%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\AKERPULS_M4_2026_PRIOR_FREEZE_V1.json" (echo ERROR: freeze JSON missing& exit /b 1)
if not exist "%OUT%\AKERPULS_M4_2026_PRIOR_FREEZE_V1.sha256" (echo ERROR: freeze SHA missing& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during M4 2026-prior freeze.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: M4 2026 prior formally frozen.
echo No model fit, prediction, fusion or geometry mutation occurred.
echo OUTPUT=%OUT%
echo NEXT STOP: inspect freeze SHA before M1 pair-prior generation.
echo ============================================================
exit /b 0
