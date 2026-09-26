@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ====================================================================================================
echo AkerVatten MVP v0a - STOPPUNKT A2 OFFICIAL SGU/SMHI SOURCE INVENTORY
echo ====================================================================================================
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

py -3 -c "import requests" >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python package requests is required.
  exit /b 1
)

echo [1/2] Offline parser regression tests...
py -3 -m unittest tests.test_akervatten_a2_source_inventory -v
if errorlevel 1 goto :fail

echo.
echo [2/2] Small official network probes...
py -3 src\93_akervatten_a2_source_inventory.py
if errorlevel 1 goto :fail

echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_A2_SOURCE_INVENTORY: PASS
echo ====================================================================================================
echo No large SGU/SMHI source dataset was downloaded.
echo No water score was frozen.
exit /b 0

:fail
echo.
echo ====================================================================================================
echo RUN_AKERVATTEN_A2_SOURCE_INVENTORY: FAIL
echo ====================================================================================================
echo Inspect work\akervatten_mvp_v0a\a2_source_inventory\source_inventory.json
exit /b 1
