@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "LOGDIR=data\derived\akerminne_v1a\skane\logs"
set "LOG=%LOGDIR%\skane_smoke.log"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo ==============================================================================
echo AkerMinne v1a - Skane smoke batch - Lomma + Ystad
echo ==============================================================================
echo Resumable. Historical raw data stays under C:\AkerSyncRaw.
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)
if not exist "config\local_paths.json" (
  echo FEL: config\local_paths.json saknas.
  exit /b 1
)
if not exist "config\akerminne_local.json" (
  echo FEL: config\akerminne_local.json saknas.
  exit /b 1
)

py -3 src\62_prepare_akerminne_skane.py > "%LOG%" 2>&1
if errorlevel 1 goto :fail

py -3 src\64_run_akerminne_skane.py --only 1262,1286 >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

py -3 src\65_verify_akerminne_skane.py --allow-partial >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

type "%LOG%"
echo.
echo ==============================================================================
echo AKERMINNE SKANE SMOKE: PASS
echo ==============================================================================
echo Lomma + Ystad ar byggda med full historik 2015-2025.
echo Nasta steg: CALL RUN_AKERMINNE_SKANE.bat
exit /b 0

:fail
type "%LOG%"
echo.
echo ==============================================================================
echo AKERMINNE SKANE SMOKE: FAIL
echo ==============================================================================
echo Returnera loggen: %LOG%
exit /b 1
