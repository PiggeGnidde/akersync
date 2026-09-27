@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ====================================================================================================
echo AkerVatten MVP v0a - STOPPUNKT B 100-FIELD END-TO-END PILOT
echo ====================================================================================================
echo.

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

where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher py saknas.
  exit /b 1
)

echo [preflight] Python dependencies...
py -3 -c "import pandas,numpy,geopandas,rasterio,requests,pyproj,xarray"
if errorlevel 1 (
  echo.
  echo FAIL: B pilot requires pandas numpy geopandas rasterio requests pyproj xarray.
  echo Paste the complete import error back to the coding chat; do not install random packages yet.
  exit /b 1
)

echo.
echo [1/2] Offline regression tests...
py -3 -m unittest tests.test_akervatten_b_pilot -v
if errorlevel 1 goto :fail

echo.
echo [2/2] Real 100-field network/data pilot...
py -3 src\94_akervatten_b_pilot.py
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_B_PILOT: PASS
echo ====================================================================================================
echo STOPPUNKT B is ready for review. No score has been frozen.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_B_PILOT: FAIL
echo ====================================================================================================
echo This is a strict pilot: paste the full output back to the coding chat.
exit /b 1
