@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "QA=data\derived\akerminne_v1a\qa"
set "PILOT=data\derived\akerminne_v1a\pilot_skurup"
set "LOGDIR=data\derived\akerminne_v1a\logs"
set "LOG=%LOGDIR%\akerminne_web_pilot.log"

echo ==============================================================================
echo AkerMinne v1a - Skurup UI pilot - STOPPUNKT E
echo ==============================================================================
echo.

if not exist "config\local_paths.json" (
  echo FEL: config\local_paths.json saknas.
  exit /b 1
)
if not exist "%QA%\akerminne_year_summary_classified.parquet" (
  echo FEL: klassificerad AkerMinne-historik saknas. Kor VERIFY_AKERMINNE_PILOT_SKURUP.bat forst.
  exit /b 1
)
if not exist "%QA%\akerminne_crop_areas_grouped.parquet" (
  echo FEL: grupperade grodkomponenter saknas.
  exit /b 1
)
if not exist "%PILOT%\akerminne_components.parquet" (
  echo FEL: raw AkerMinne components saknas.
  exit /b 1
)
if not exist "dist\municipalities.json" (
  echo FEL: befintlig AkerPass dist saknas. Kor BUILD_AKERPASS_WEB_V1.bat forst.
  exit /b 1
)
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if errorlevel 1 exit /b 1
where py >nul 2>nul
if errorlevel 1 (
  echo FEL: Python-launchern py saknas.
  exit /b 1
)

py -3 src\57_build_akerminne_web_pilot.py > "%LOG%" 2>&1
if errorlevel 1 goto :fail
py -3 src\42_build_akerpass_frontend.py >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
py -3 src\59_patch_akerpass_akerminne_ui.py >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
py -3 src\61_revise_akerminne_ui_copy.py >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
py -3 src\43_verify_akerpass_web_v1.py >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
py -3 src\58_verify_akerminne_web_pilot.py >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

type "%LOG%"
echo.
echo ==============================================================================
echo AKERMINNE SKURUP UI PILOT: PASS
echo ==============================================================================
echo Oppna via lokal webbserver:
echo   CALL START_AKERPASS_LOCAL.bat
echo och ga till:
echo   http://localhost:8000/?kommun=Skurup
echo.
echo STOPPUNKT E - kontrollera desktop + mobil innan Skane-skalning.
exit /b 0

:fail
type "%LOG%"
echo.
echo ==============================================================================
echo AKERMINNE SKURUP UI PILOT: FAIL
echo ==============================================================================
echo Returnera hela loggen: %LOG%
exit /b 1
