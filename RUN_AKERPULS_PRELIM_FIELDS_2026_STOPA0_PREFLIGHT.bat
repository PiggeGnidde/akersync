@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_stopa0"
set "LOCAL_PATHS=%CD%\config\local_paths.json"
if not "%~1"=="" set "OUT=%~1"
if not "%~2"=="" set "LOCAL_PATHS=%~2"

echo ========================================================================================
echo AkerPuls preliminara skiften 2026 - STOPPUNKT A0 PREFLIGHT
echo ========================================================================================
echo Output:      %OUT%
echo Local paths: %LOCAL_PATHS%
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean.
  git status --short
  exit /b 1
)
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)
where py >nul 2>nul || (echo FAIL: Python launcher 'py' missing.& exit /b 1)
if not exist "%LOCAL_PATHS%" (echo FAIL: missing %LOCAL_PATHS%& exit /b 1)
if "%CDSE_CLIENT_ID%"=="" (echo BLOCKED_CREDENTIALS: CDSE_CLIENT_ID is not set in this cmd.exe window.& exit /b 1)
if "%CDSE_CLIENT_SECRET%"=="" (echo BLOCKED_CREDENTIALS: CDSE_CLIENT_SECRET is not set in this cmd.exe window.& exit /b 1)
py -3 -c "import geopandas, shapely" >nul 2>nul || (echo FAIL: Python needs geopandas and shapely.& exit /b 1)
if not exist "%OUT%\logs" mkdir "%OUT%\logs"

py -3 -m unittest tests.test_akerpuls_prelim_fields_2026_stopa0 -v > "%OUT%\logs\tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\tests.log"
if not "%RC%"=="0" goto :fail

py -3 src\106_akerpuls_prelim_fields_2026_stopa0_preflight.py --local-paths "%LOCAL_PATHS%" --output-dir "%OUT%" > "%OUT%\logs\preflight.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\preflight.log"
if not "%RC%"=="0" goto :fail

for %%F in (
  "%OUT%\scene_inventory.csv"
  "%OUT%\snapshot_coverage.csv"
  "%OUT%\tile_plan.csv"
  "%OUT%\tile_plan.gpkg"
  "%OUT%\preflight_manifest.json"
  "%OUT%\preflight_qa.md"
) do if not exist "%%~F" (echo FAIL: missing artifact %%~F& goto :fail)

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: preflight changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo ========================================================================================
echo STOPPUNKT A0 PREFLIGHT: PASS
echo ========================================================================================
echo No Sentinel-2 mass download was performed.
echo Return these to ChatGPT:
echo   1. Complete console output above
echo   2. %OUT%\preflight_qa.md
echo   3. %OUT%\preflight_manifest.json
echo.
exit /b 0

:fail
echo.
echo ========================================================================================
echo STOPPUNKT A0 PREFLIGHT: FAIL OR REVIEW REQUIRED
echo ========================================================================================
echo Return %OUT%\logs\preflight.log and %OUT%\logs\tests.log to ChatGPT.
exit /b 1
