@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "LOCAL_CFG=config\akerminne_local.json"
set "LOCAL_EXAMPLE=config\akerminne_local.example.json"
set "PROJECT_CFG=config\local_paths.json"
set "OUTDIR=data\derived\akerminne_v1a\discovery"
set "LOGDIR=data\derived\akerminne_v1a\logs"
set "LOG=%LOGDIR%\akerminne_discovery.log"

echo ==============================================================================
echo AkerMinne v1a - discovery only - STOPPUNKT A
echo ==============================================================================
echo.

if not exist "%PROJECT_CFG%" (
  echo FEL: %PROJECT_CFG% saknas.
  echo Kor SETUP_PATHS.bat forst; discovery ska ateranvanda befintlig 2025-konfiguration.
  exit /b 1
)

if not exist "%LOCAL_CFG%" (
  if not exist "%LOCAL_EXAMPLE%" (
    echo FEL: %LOCAL_EXAMPLE% saknas.
    exit /b 1
  )
  copy /Y "%LOCAL_EXAMPLE%" "%LOCAL_CFG%" >nul
  if errorlevel 1 (
    echo FEL: kunde inte skapa %LOCAL_CFG%.
    exit /b 1
  )
  echo Skapade lokal AkerMinne-konfiguration: %LOCAL_CFG%
  echo Standard raw_root ar C:\AkerSyncRaw. Andra sokvagar kan senare anges i denna Git-ignorerade fil.
  echo.
)

if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if errorlevel 1 exit /b 1
if not exist "%OUTDIR%" mkdir "%OUTDIR%"
if errorlevel 1 exit /b 1

where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern 'py' saknas. Kor INSTALL_REQUIREMENTS.bat i samma miljo som tidigare AkerSync-korningar.
  exit /b 1
)

py -3 src\50_akerminne_discovery.py --local-config "%LOCAL_CFG%" --project-local-config "%PROJECT_CFG%" > "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
type "%LOG%"

if not "%RC%"=="0" goto :fail
if not exist "%OUTDIR%\discovery_report.md" goto :missing
if not exist "%OUTDIR%\schema_summary.json" goto :missing

echo.
echo ==============================================================================
echo DISCOVERY RUNNER: PASS
echo ==============================================================================
echo Returnera vid STOPPUNKT A:
echo   %OUTDIR%\discovery_report.md
echo   %OUTDIR%\schema_summary.json
echo   %LOG%
echo.
exit /b 0

:missing
echo.
echo FEL: discovery avslutades utan obligatoriska rapportfiler.
goto :fail

:fail
echo.
echo ==============================================================================
echo DISCOVERY RUNNER: FAIL
echo ==============================================================================
echo Returnera hela loggen: %LOG%
exit /b 1
