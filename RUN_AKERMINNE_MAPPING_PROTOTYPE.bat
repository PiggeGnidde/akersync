@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "PROJECT_CFG=config\local_paths.json"
set "LOCAL_CFG=config\akerminne_local.json"
set "LOGDIR=data\derived\akerminne_v1a\logs"
set "LOG=%LOGDIR%\akerminne_mapping_prototype.log"
set "REPORT=data\derived\akerminne_v1a\mapping_prototype\mapping_prototype_report.md"

echo ==============================================================================
echo AkerMinne v1a - geometry mapping prototype - STOPPUNKT B
echo ==============================================================================
echo.

if not exist "%PROJECT_CFG%" (
  echo FEL: %PROJECT_CFG% saknas.
  exit /b 1
)
if not exist "%LOCAL_CFG%" (
  echo FEL: %LOCAL_CFG% saknas. Kor RUN_AKERMINNE_DISCOVERY.bat forst.
  exit /b 1
)
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if errorlevel 1 exit /b 1

where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

py -3 src\52_akerminne_mapping_prototype.py --local-config "%LOCAL_CFG%" --project-local-config "%PROJECT_CFG%" > "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
type "%LOG%"
if not "%RC%"=="0" goto :fail
if not exist "%REPORT%" (
  echo FEL: obligatorisk rapport saknas: %REPORT%
  goto :fail
)

echo.
echo ==============================================================================
echo MAPPING PROTOTYPE RUNNER: PASS
echo ==============================================================================
echo STOPPUNKT B - returnera:
echo   %LOG%
echo   %REPORT%
echo.
exit /b 0

:fail
echo.
echo ==============================================================================
echo MAPPING PROTOTYPE RUNNER: FAIL
echo ==============================================================================
echo Returnera hela loggen: %LOG%
exit /b 1
