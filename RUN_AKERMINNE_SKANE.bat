@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "LOGDIR=data\derived\akerminne_v1a\skane\logs"
set "LOG=%LOGDIR%\skane_full.log"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo ==============================================================================
echo AkerMinne v1a - FULL SKANE 33 municipalities
echo ==============================================================================
echo Resumable municipality-by-municipality and year-by-year.
echo Safe to rerun after interruption.
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

py -3 src\64_run_akerminne_skane.py >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

py -3 src\65_verify_akerminne_skane.py >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

type "%LOG%"
echo.
echo ==============================================================================
echo AKERMINNE FULL SKANE: PASS
echo ==============================================================================
echo QA:
echo   data\derived\akerminne_v1a\skane\skane_qa.md
echo Progress:
echo   data\derived\akerminne_v1a\skane\progress.json
exit /b 0

:fail
type "%LOG%"
echo.
echo ==============================================================================
echo AKERMINNE FULL SKANE: FAIL
echo ==============================================================================
echo Alla klara kommuner/ar ar checkpointade.
echo Korrigera felet och kor samma kommando igen.
echo Returnera loggen: %LOG%
exit /b 1
