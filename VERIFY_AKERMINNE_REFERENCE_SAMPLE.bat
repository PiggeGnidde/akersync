@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "PROJECT_CFG=config\local_paths.json"
set "QA=data\derived\akerminne_v1a\qa"
set "LOGDIR=data\derived\akerminne_v1a\logs"
set "LOG=%LOGDIR%\akerminne_reference_sample.log"
set "REPORT=%QA%\reference_sample_qa.md"

echo ==============================================================================
echo AkerMinne v1a - representative reference sample - STOPPUNKT D
echo ==============================================================================
echo.

if not exist "%PROJECT_CFG%" (
  echo FEL: %PROJECT_CFG% saknas.
  exit /b 1
)
if not exist "%QA%\akerminne_year_summary_classified.parquet" (
  echo FEL: klassificerad pilot saknas. Kor VERIFY_AKERMINNE_PILOT_SKURUP.bat forst.
  exit /b 1
)
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if errorlevel 1 exit /b 1

py -3 src\55_build_akerminne_reference_sample.py --project-local-config "%PROJECT_CFG%" > "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
type "%LOG%"
if not "%RC%"=="0" goto :fail
if not exist "%REPORT%" goto :missing
if not exist "%QA%\reference_sample_checklist.csv" goto :missing
if not exist "%QA%\reference_sample_fields.geojson" goto :missing

echo.
echo ==============================================================================
echo AKERMINNE REFERENCE SAMPLE: PASS
echo ==============================================================================
echo STOPPUNKT D - returnera:
echo   %REPORT%
echo   %QA%\reference_sample_checklist.csv
echo.
exit /b 0

:missing
echo FEL: referenssteget avslutades utan obligatorisk output.
:fail
echo.
echo ==============================================================================
echo AKERMINNE REFERENCE SAMPLE: FAIL
echo ==============================================================================
echo Returnera hela loggen: %LOG%
exit /b 1
