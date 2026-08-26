@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "LOCAL_CFG=config\akerminne_local.json"
set "PROJECT_CFG=config\local_paths.json"
set "QA=data\derived\akerminne_v1a\qa"
set "HTML=%QA%\akerminne_visual_qa.html"
set "LOGDIR=data\derived\akerminne_v1a\logs"
set "LOG=%LOGDIR%\akerminne_visual_qa.log"

echo ==============================================================================
echo AkerMinne v1a - visual geometry QA - STOPPUNKT D
echo ==============================================================================
echo.

if not exist "%LOCAL_CFG%" (
  echo FEL: %LOCAL_CFG% saknas.
  exit /b 1
)
if not exist "%PROJECT_CFG%" (
  echo FEL: %PROJECT_CFG% saknas.
  exit /b 1
)
if not exist "%QA%\reference_sample_checklist.csv" (
  echo FEL: representativt referensurval saknas. Kor VERIFY_AKERMINNE_REFERENCE_SAMPLE.bat forst.
  exit /b 1
)
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if errorlevel 1 exit /b 1
where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

py -3 src\56_build_akerminne_visual_qa.py --local-config "%LOCAL_CFG%" --project-local-config "%PROJECT_CFG%" > "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
type "%LOG%"
if not "%RC%"=="0" goto :fail
if not exist "%HTML%" goto :missing

start "" "%HTML%"

echo.
echo ==============================================================================
echo AKERMINNE VISUAL QA: BUILT
echo ==============================================================================
echo Granska alla 20 fallen i webblasaren.
echo Markera OK eller GRANSKA och skriv eventuell kommentar.
echo Klicka sedan "Exportera review CSV".
echo Returnera filen akerminne_visual_review.csv hit i chatten.
echo.
echo Detta ar fortfarande STOPPUNKT D - ingen publik UI har byggts.
exit /b 0

:missing
echo FEL: HTML-filen skapades inte: %HTML%
:fail
echo.
echo ==============================================================================
echo AKERMINNE VISUAL QA: FAIL
echo ==============================================================================
echo Returnera hela loggen: %LOG%
exit /b 1
