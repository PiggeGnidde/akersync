@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ====================================================================================================
echo AkerVatten H2 - PRODUCT DIMENSIONS WITHOUT COMPOSITE WATER SCORE
echo ====================================================================================================
echo.
echo Builds product-ready evidence dimensions from frozen F/G + H0/H1.
echo No overall water score, legal verdict or traffic-light permission signal is created.
echo.

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akervatten-mvp-v0a" (
  echo FAIL: expected feature/akervatten-mvp-v0a, got %BRANCH%.
  exit /b 1
)

py -3 -c "import pandas,numpy,pyarrow"
if errorlevel 1 exit /b 1

echo [1/2] Offline regression tests...
py -3 -m unittest tests.test_akervatten_h2_product_dimensions -v
if errorlevel 1 goto :fail

echo.
echo [2/2] Build product dimensions...
py -3 src\110_akervatten_h2_product_dimensions.py
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_H2_PRODUCT_DIMENSIONS: PASS
echo ====================================================================================================
echo Paste the full output back to the coding chat before H2 is frozen.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_H2_PRODUCT_DIMENSIONS: FAIL
echo ====================================================================================================
exit /b 1
