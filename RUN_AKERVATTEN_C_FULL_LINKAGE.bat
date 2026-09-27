@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ====================================================================================================
echo AkerVatten MVP v0a - STOPPUNKT C FULL SKANE LINKAGE
echo ====================================================================================================
echo.
echo This run is resumable. Completed source tiles and every 1000-field checkpoint are reused.
echo It is safe to run the same command again after Ctrl-C, reboot, network loss, or shutdown.
echo.

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="feature/akervatten-mvp-v0a" (
  echo FAIL: expected feature/akervatten-mvp-v0a, got %BRANCH%.
  exit /b 1
)

where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher py is missing.
  exit /b 1
)

echo [preflight] Python dependencies...
py -3 -c "import pandas,numpy,geopandas,rasterio,requests,pyproj,xlrd,pyarrow"
if errorlevel 1 (
  echo.
  echo FAIL: C requires pandas numpy geopandas rasterio requests pyproj xlrd pyarrow.
  echo Paste the complete import error back to the coding chat.
  exit /b 1
)

echo.
echo [1/2] Offline regression tests...
py -3 -m unittest tests.test_akervatten_c_full_linkage -v
if errorlevel 1 goto :fail

echo.
echo [2/2] Full resumable Skane linkage...
py -3 src\96_akervatten_c_full_linkage.py
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_C_FULL_LINKAGE: PASS
echo ====================================================================================================
echo Paste the final COVERAGE and HYDROLOGICAL REUSE blocks back to the coding chat before C is frozen.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_C_FULL_LINKAGE: FAIL
echo ====================================================================================================
echo Re-run the same command after any fix or interruption; valid checkpoints are preserved.
exit /b 1
