@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ====================================================================================================
echo AkerVatten MVP v0a - STOPPUNKT E2 FOCUSED REVIEW
echo ====================================================================================================
echo.
echo Reviews:
echo   - SGU situation vs fill directional tension
echo   - dates/years of longest low-groundwater episodes
echo   - seasonality dependence
echo   - missed slope/relief-like local columns
echo   - surface-water redundancy
echo No score is frozen.
echo.

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akervatten-mvp-v0a" (
  echo FAIL: expected feature/akervatten-mvp-v0a, got %BRANCH%.
  exit /b 1
)

py -3 -c "import pandas,numpy,pyarrow"
if errorlevel 1 (
  echo FAIL: E2 requires pandas numpy pyarrow.
  exit /b 1
)

echo [1/2] Offline regression tests...
py -3 -m unittest tests.test_akervatten_e2_review -v
if errorlevel 1 goto :fail

echo.
echo [2/2] Focused review...
py -3 src\99_akervatten_e2_review.py
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_E2_REVIEW: PASS
echo ====================================================================================================
echo Paste the full output back to the coding chat before E is frozen.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_E2_REVIEW: FAIL
echo ====================================================================================================
exit /b 1
