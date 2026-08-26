@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "LOGDIR=data\derived\akerminne_v1a\logs"
set "OUTDIR=data\derived\akerminne_v1a\mapping_qa"
set "LOG=%LOGDIR%\akerminne_mapping_qa.log"

if not exist "config\local_paths.json" (
  echo FEL: config\local_paths.json saknas.
  exit /b 1
)
if not exist "config\akerminne_local.json" (
  echo FEL: config\akerminne_local.json saknas. Kor discovery/pilotdata forst.
  exit /b 1
)
if not exist "data\derived\akerminne_v1a\mapping_prototype\mapping_prototype_report.json" (
  echo FEL: mapping prototype saknas. Kor RUN_AKERMINNE_MAPPING_PROTOTYPE.bat forst.
  exit /b 1
)

if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if not exist "%OUTDIR%" mkdir "%OUTDIR%"

py -3 src\53_akerminne_mapping_qa.py > "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
type "%LOG%"

if not "%RC%"=="0" goto :fail
if not exist "%OUTDIR%\mapping_qa_report.md" goto :fail
if not exist "%OUTDIR%\mapping_qa_report.json" goto :fail

echo.
echo ==============================================================================
echo MAPPING QA RUNNER: PASS
echo ==============================================================================
echo STOPPUNKT B - returnera:
echo   %OUTDIR%\mapping_qa_report.md
echo   %LOG%
exit /b 0

:fail
echo.
echo ==============================================================================
echo MAPPING QA RUNNER: FAIL
echo ==============================================================================
echo Returnera hela loggen: %LOG%
exit /b 1
