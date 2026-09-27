@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ====================================================================================================
echo AkerVatten MVP v0a - STOPPUNKT D HISTORICAL RAW FEATURES
echo ====================================================================================================
echo.
echo Resumable:
echo   - every completed SGU-HYPE history file is cached individually
echo   - groundwater feature extraction checkpoints every 25 areas
echo   - field joins checkpoint every 5000 fields
echo Re-run this same BAT after Ctrl-C, reboot, shutdown or network interruption.
echo.

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akervatten-mvp-v0a" (
  echo FAIL: expected feature/akervatten-mvp-v0a, got %BRANCH%.
  exit /b 1
)

echo [preflight] Python dependencies...
py -3 -c "import pandas,numpy,requests,xlrd,pyarrow"
if errorlevel 1 (
  echo.
  echo FAIL: D requires pandas numpy requests xlrd pyarrow.
  echo Paste the complete import error back to the coding chat.
  exit /b 1
)

echo.
echo [1/2] Offline regression tests...
py -3 -m unittest tests.test_akervatten_d_history_features -v
if errorlevel 1 goto :fail

echo.
echo [2/2] Resumable historical feature run...
py -3 src\97_akervatten_d_history_features.py
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_D_HISTORY_FEATURES: PASS
echo ====================================================================================================
echo Paste QA COVERAGE and RAW FEATURE DISTRIBUTIONS back to the coding chat before D is frozen.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_D_HISTORY_FEATURES: FAIL
echo ====================================================================================================
echo All completed source files/checkpoints are preserved. Re-run the same BAT after the fix.
exit /b 1
