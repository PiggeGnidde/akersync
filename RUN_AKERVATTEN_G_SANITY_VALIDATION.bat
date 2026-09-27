@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ====================================================================================================
echo AkerVatten MVP v0a - STOPPUNKT G GEOGRAPHIC / AGRONOMIC SANITY VALIDATION
echo ====================================================================================================
echo.
echo Frozen F formulas are not changed.
echo Produces distributions, fixed bands, hydrological invariants, extremes, group enrichment,
echo representative cases, contrast counts and product explanation copy.
echo No combined AkerVatten index is created.
echo.

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akervatten-mvp-v0a" (
  echo FAIL: expected feature/akervatten-mvp-v0a, got %BRANCH%.
  exit /b 1
)

py -3 -c "import pandas,numpy,pyarrow"
if errorlevel 1 exit /b 1

echo [1/2] Offline regression tests...
py -3 -m unittest tests.test_akervatten_g_sanity_validation -v
if errorlevel 1 goto :fail

echo.
echo [2/2] Sanity validation...
py -3 src\105_akervatten_g_sanity_validation.py
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_G_SANITY_VALIDATION: PASS
echo ====================================================================================================
echo Paste the full output back to the coding chat before G is frozen.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_G_SANITY_VALIDATION: FAIL
echo ====================================================================================================
exit /b 1
