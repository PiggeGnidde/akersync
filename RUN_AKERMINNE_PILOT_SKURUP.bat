@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "LOCAL_CFG=config\akerminne_local.json"
set "PROJECT_CFG=config\local_paths.json"
set "LOGDIR=data\derived\akerminne_v1a\logs"
set "LOG=%LOGDIR%\akerminne_phase3_skurup.log"
set "REPORT=data\derived\akerminne_v1a\pilot_skurup\phase3_report.md"

echo ==============================================================================
echo AkerMinne v1a - full Skurup raw history 2015-2025 - STOPPUNKT C
echo ==============================================================================
echo.

if not exist "%LOCAL_CFG%" (
  echo FEL: %LOCAL_CFG% saknas. Kor RUN_AKERMINNE_DISCOVERY.bat forst.
  exit /b 1
)
if not exist "%PROJECT_CFG%" (
  echo FEL: %PROJECT_CFG% saknas.
  exit /b 1
)
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if errorlevel 1 exit /b 1
where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

rem Historiska ar. 2015 och 2020 ateranvands fran cache; ovriga hamtas resumable.
py -3 src\51_download_akerminne_pilot.py --years 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024 > "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :fail

py -3 src\53_build_akerminne_history.py --local-config "%LOCAL_CFG%" --project-local-config "%PROJECT_CFG%" --years 2015:2025 --resume >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
type "%LOG%"
if not "%RC%"=="0" goto :fail_after_type
if not exist "%REPORT%" (
  echo FEL: obligatorisk rapport saknas: %REPORT%
  goto :fail_after_type
)

echo.
echo ==============================================================================
echo AKERMINNE SKURUP PHASE 3 RUNNER: PASS
echo ==============================================================================
echo STOPPUNKT C - returnera:
echo   %LOG%
echo   %REPORT%
echo   data\derived\akerminne_v1a\pilot_skurup\unknown_crop_codes.csv
echo.
exit /b 0

:fail
type "%LOG%"
:fail_after_type
echo.
echo ==============================================================================
echo AKERMINNE SKURUP PHASE 3 RUNNER: FAIL
echo ==============================================================================
echo Returnera hela loggen: %LOG%
exit /b 1
