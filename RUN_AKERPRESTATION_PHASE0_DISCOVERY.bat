@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerprestation-foundation-v0a"
set "BASE_TAG=akerminne-v1.0"
set "BASE_COMMIT=4b53ab24e9822f1c36c6cc31931dba3c1855fead"
set "PROJECT_CFG=config\local_paths.json"
set "AKERMINNE_CFG=config\akerminne_local.json"
set "AKERMINNE_EXAMPLE=config\akerminne_local.example.json"
set "OUTDIR=data\derived\akerprestation_phase0\discovery"
set "MANIFEST=data\derived\akerprestation_phase0\manifests\discovery_manifest.json"
set "LOGDIR=data\derived\akerprestation_phase0\logs"
set "TESTLOG=%LOGDIR%\discovery_tests.log"
set "RUNLOG=%LOGDIR%\discovery.log"

echo ==============================================================================
echo AkerPrestation phase 0 - DISCOVERY ONLY - STOPPUNKT A
echo ==============================================================================
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FEL: working tree is not clean. Stop before discovery.
  git status --short
  exit /b 1
)

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FEL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)

for /f "delims=" %%T in ('git rev-list -n 1 "%BASE_TAG%"') do set "TAGSHA=%%T"
if /I not "%TAGSHA%"=="%BASE_COMMIT%" (
  echo FEL: %BASE_TAG% points to %TAGSHA%, expected %BASE_COMMIT%.
  exit /b 1
)

git merge-base --is-ancestor "%BASE_COMMIT%" HEAD
if errorlevel 1 (
  echo FEL: current HEAD does not descend from frozen AkerMinne v1 base.
  exit /b 1
)

if not exist "%PROJECT_CFG%" (
  echo FEL: %PROJECT_CFG% saknas. Discovery ateranvander AkerSync befintliga 2025-konfiguration.
  exit /b 1
)

if not exist "%AKERMINNE_CFG%" (
  if not exist "%AKERMINNE_EXAMPLE%" (
    echo FEL: %AKERMINNE_EXAMPLE% saknas.
    exit /b 1
  )
  copy /Y "%AKERMINNE_EXAMPLE%" "%AKERMINNE_CFG%" >nul
  if errorlevel 1 exit /b 1
  echo Skapade lokal Git-ignorerad konfiguration: %AKERMINNE_CFG%
)

where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern 'py' saknas. Kor INSTALL_REQUIREMENTS.bat och aterkom.
  exit /b 1
)

if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if errorlevel 1 exit /b 1

echo [1/2] Discovery unit tests...
py -3 -m unittest discover -s tests -p "test_akerprestation_phase0_discovery.py" -v > "%TESTLOG%" 2>&1
set "RC=%ERRORLEVEL%"
type "%TESTLOG%"
if not "%RC%"=="0" goto :fail

echo.
echo [2/2] Repository + raw/source discovery...
py -3 src\70_akerprestation_phase0_discovery.py --project-config "%PROJECT_CFG%" --akerminne-local "%AKERMINNE_CFG%" > "%RUNLOG%" 2>&1
set "RC=%ERRORLEVEL%"
type "%RUNLOG%"
if not "%RC%"=="0" goto :fail

for %%F in (
  "%OUTDIR%\discovery_report.md"
  "%OUTDIR%\repository_summary.json"
  "%OUTDIR%\soil_class_schema.json"
  "%OUTDIR%\sko_schema.json"
  "%MANIFEST%"
) do (
  if not exist "%%~F" (
    echo FEL: obligatorisk discoveryartefakt saknas: %%~F
    goto :fail
  )
)

for /f "delims=" %%S in ('git status --short') do (
  echo FEL: discovery changed Git-visible files. Stop.
  git status --short
  goto :fail
)

echo.
echo ==============================================================================
echo DISCOVERY RUNNER: PASS
echo ==============================================================================
echo Klass 5: redan implementerad i frozen baseline; ny klass-scope ar 1-4.
echo Ingen overlaymotor, pilot, Skane-korning eller webb har korts.
echo.
echo STOPPUNKT A - returnera:
echo   1. Hela PASS/FAIL-sammanfattningen ovan
echo   2. %OUTDIR%\discovery_report.md
echo   3. %OUTDIR%\soil_class_schema.json
echo   4. %OUTDIR%\sko_schema.json
echo   5. sources/source_hashes-sektionen ur %MANIFEST%
echo   6. Alla WARN, ERROR och BLOCKED-rader fran %RUNLOG% och rapporten
echo.
echo Fulla loggar:
echo   %TESTLOG%
echo   %RUNLOG%
exit /b 0

:fail
echo.
echo ==============================================================================
echo DISCOVERY RUNNER: FAIL
echo ==============================================================================
echo Returnera hela loggarna:
echo   %TESTLOG%
echo   %RUNLOG%
exit /b 1
