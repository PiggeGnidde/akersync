@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ====================================================================================================
echo AkerVatten H0 - STORA GRUNDVATTENMAGASIN - SKANE INVENTORY
echo ====================================================================================================
echo.
echo Downloads/caches SGU Grundvattenmagasin, joins all 128636 field representative points,
echo preserves vertically stacked magazines, withdrawal classes and recharge-area relations.
echo No new 0-100 score is created.
echo.

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akervatten-mvp-v0a" (
  echo FAIL: expected feature/akervatten-mvp-v0a, got %BRANCH%.
  exit /b 1
)

py -3 -c "import pandas,geopandas,pyarrow,pyproj,requests"
if errorlevel 1 exit /b 1

echo [1/2] Offline regression tests...
py -3 -m unittest tests.test_akervatten_h0_large_groundwater_inventory -v
if errorlevel 1 goto :fail

echo.
echo [2/2] Full Skane inventory...
py -3 src\108_akervatten_h0_large_groundwater_inventory.py
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_H0_LARGE_GROUNDWATER: PASS
echo ====================================================================================================
echo Paste the full output back to the coding chat before any H0 interpretation/freeze.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_H0_LARGE_GROUNDWATER: FAIL
echo ====================================================================================================
exit /b 1
