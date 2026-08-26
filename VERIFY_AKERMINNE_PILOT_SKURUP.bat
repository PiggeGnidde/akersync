@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "PROJECT_CFG=config\local_paths.json"
set "PILOT=data\derived\akerminne_v1a\pilot_skurup"
set "QA=data\derived\akerminne_v1a\qa"
set "LOGDIR=data\derived\akerminne_v1a\logs"
set "LOG=%LOGDIR%\akerminne_verify_skurup.log"
set "REPORT=%QA%\akerminne_pilot_qa.md"

echo ==============================================================================
echo AkerMinne v1a - verify Skurup pilot - STOPPUNKT D
echo ==============================================================================
echo.

if not exist "%PROJECT_CFG%" (
  echo FEL: %PROJECT_CFG% saknas.
  exit /b 1
)
if not exist "%PILOT%\akerminne_year_summary.parquet" (
  echo FEL: Phase 3 summary saknas. Kor RUN_AKERMINNE_PILOT_SKURUP.bat forst.
  exit /b 1
)
if not exist "%PILOT%\akerminne_components.parquet" (
  echo FEL: Phase 3 components saknas. Kor RUN_AKERMINNE_PILOT_SKURUP.bat forst.
  exit /b 1
)
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if errorlevel 1 exit /b 1
where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

py -3 src\54_verify_akerminne_pilot.py --project-local-config "%PROJECT_CFG%" > "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
type "%LOG%"
if not "%RC%"=="0" goto :fail
if not exist "%REPORT%" goto :missing
if not exist "%QA%\problem_fields.geojson" goto :missing
if not exist "%QA%\manual_checklist.csv" goto :missing

echo.
echo ==============================================================================
echo AKERMINNE PILOT VERIFY: PASS
echo ==============================================================================
echo STOPPUNKT D - returnera:
echo   %REPORT%
echo   %QA%\manual_checklist.csv
echo.
exit /b 0

:missing
echo FEL: verifieringen avslutades utan obligatorisk QA-output.
:fail
echo.
echo ==============================================================================
echo AKERMINNE PILOT VERIFY: FAIL
echo ==============================================================================
echo Returnera hela loggen: %LOG%
exit /b 1
