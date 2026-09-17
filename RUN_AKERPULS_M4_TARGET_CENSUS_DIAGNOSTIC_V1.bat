@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_m4_target_census_diagnostic_v1"
if not "%~1"=="" set "OUT=%~1"

echo ============================================================
echo AKERPULS - M4 TARGET CENSUS DIAGNOSTIC V1
echo READ-ONLY QA RULE DIAGNOSTIC; NO MODEL FIT
echo ============================================================
echo OUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before target-census diagnostic.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)
if exist "%OUT%" (
  echo ERROR: output directory already exists: %OUT%
  echo Preserve prior evidence. Use a new output directory for a deliberate rerun.
  exit /b 1
)

echo.
echo [1/2] Unit tests
py -3 -m unittest tests.test_akerpuls_m4_target_census_diagnostic_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Diagnose exact historical target-validity rule
py -3 -u src\180_akerpuls_m4_target_census_diagnostic_v1.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\M4_TARGET_CENSUS_DIAGNOSTIC_V1.json" (echo ERROR: diagnostic JSON missing& exit /b 1)
if not exist "%OUT%\M4_TARGET_CENSUS_DIAGNOSTIC_V1.csv" (echo ERROR: diagnostic CSV missing& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during target-census diagnostic.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: target-census QA diagnostic completed read-only.
echo No model fit or 2026 prediction occurred.
echo OUTPUT=%OUT%
echo NEXT STOP: inspect exact matching validity rule before patching reproduction gate.
echo ============================================================
exit /b 0
