@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ====================================================================================================
echo AkerVatten MVP v0a - STOPPUNKT F2 MARKVATA DISTINCTNESS REVIEW
echo ====================================================================================================
echo.
echo F passed QA, but MarkTorka vs MarkVata had rho=-0.924.
echo F2 compares transparent joint-evidence wetness aggregation before F is frozen.
echo No combined score is created.
echo.

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akervatten-mvp-v0a" (
  echo FAIL: expected feature/akervatten-mvp-v0a, got %BRANCH%.
  exit /b 1
)

py -3 -c "import pandas,numpy,pyarrow"
if errorlevel 1 exit /b 1

echo [1/2] Offline regression tests...
py -3 -m unittest tests.test_akervatten_f2_markvata_review -v
if errorlevel 1 goto :fail

echo.
echo [2/2] MarkVata distinctness review...
py -3 src\101_akervatten_f2_markvata_review.py
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_F2_MARKVATA_REVIEW: PASS
echo ====================================================================================================
echo Paste the full output back to the coding chat before F is frozen.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_F2_MARKVATA_REVIEW: FAIL
echo ====================================================================================================
exit /b 1
