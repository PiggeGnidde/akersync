@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "LEGACY=C:\AkerSyncRepo"
set "PRESTATION=C:\AkerSync-Prestation"
if not "%~1"=="" set "LEGACY=%~f1"
if not "%~2"=="" set "PRESTATION=%~f2"

echo ====================================================================================================
echo AkerVatten MVP v0a - STOPPUNKT A1b COVERAGE / SCHEMA AUDIT
echo ====================================================================================================
echo Legacy source root: %LEGACY%
echo Prestation root:    %PRESTATION%
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher py saknas.
  exit /b 1
)

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: AkerVatten worktree is not clean.
  git status --short
  exit /b 1
)

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akervatten-mvp-v0a" (
  echo FAIL: expected feature/akervatten-mvp-v0a, got %BRANCH%.
  exit /b 1
)

echo [1/2] Regression tests...
py -3 -m unittest tests.test_akervatten_a1b_coverage_schema -v
if errorlevel 1 goto :fail

echo.
echo [2/2] Full-population coverage and static-context schema audit...
py -3 src\92_akervatten_a1b_coverage_schema.py --legacy-root "%LEGACY%" --prestation-root "%PRESTATION%"
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_A1B_COVERAGE_SCHEMA: PASS
echo ====================================================================================================
echo No new water score frozen.
echo No external downloads performed.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_A1B_COVERAGE_SCHEMA: FAIL
echo ====================================================================================================
exit /b 1
