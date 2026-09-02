@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/rapskartan-skane-v1a"
set "RAW_ROOT=C:\AkerSyncRaw"
set "STOP_A=C:\AkerSyncRepo\work\rapskartan_skane_v1_discovery_stopA"
set "OUT=C:\AkerSyncRepo\work\rapskartan_skane_v1_s2_pilot_stopB"
set "CACHE=C:\AkerSyncRaw\rapskartan_v1\sentinel2_l2a\datapilot_v1"
if not "%~1"=="" set "RAW_ROOT=%~1"
if not "%~2"=="" set "OUT=%~2"
if not "%~3"=="" set "CACHE=%~3"
if not "%~4"=="" set "STOP_A=%~4"

echo ========================================================================================
echo Rapskartan Skane V1 - BOUNDED SENTINEL-2 DATAPILOT - STOPPUNKT B
echo ========================================================================================
echo Raw root:       %RAW_ROOT%
echo Accepted StopA: %STOP_A%
echo Output:         %OUT%
echo Content cache:  %CACHE%
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before datapilot.
  git status --short
  exit /b 1
)
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)
where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher 'py' is missing.
  exit /b 1
)
if "%CDSE_CLIENT_ID%"=="" (
  echo BLOCKED_CREDENTIALS: CDSE_CLIENT_ID is not set in this cmd.exe window.
  exit /b 1
)
if "%CDSE_CLIENT_SECRET%"=="" (
  echo BLOCKED_CREDENTIALS: CDSE_CLIENT_SECRET is not set in this cmd.exe window.
  exit /b 1
)
py -3 -c "import geopandas, matplotlib, pandas, PIL, shapely" >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python needs geopandas, matplotlib, pandas, Pillow and shapely for the datapilot.
  exit /b 1
)
if not exist "%STOP_A%\discovery_manifest.json" (
  echo FAIL: accepted STOPPUNKT A manifest is missing: %STOP_A%\discovery_manifest.json
  exit /b 1
)
if not exist "%OUT%\logs" mkdir "%OUT%\logs"
if errorlevel 1 exit /b 1

echo [1/2] Datapilot contracts, blind guards, cache and parser tests...
py -3 -m unittest tests.test_rapskartan_v1_discovery tests.test_rapskartan_s2_pilot -v > "%OUT%\logs\s2_pilot_tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\s2_pilot_tests.log"
if not "%RC%"=="0" goto :fail

echo.
echo [2/2] Bounded pre-2025 field time series, SCL/edge QA and offline hash rerun...
py -3 src\92_run_rapskartan_s2_pilot.py --raw-root "%RAW_ROOT%" --stop-a-dir "%STOP_A%" --output-dir "%OUT%" --cache-root "%CACHE%" > "%OUT%\logs\s2_pilot.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\s2_pilot.log"
if not "%RC%"=="0" goto :fail

for %%F in (
  "%OUT%\s2_pilot_contract.json"
  "%OUT%\pilot_selection.csv"
  "%OUT%\field_timeseries.csv"
  "%OUT%\scl_timeseries.csv"
  "%OUT%\edge_rule_summary.csv"
  "%OUT%\cloud_mask_examples.csv"
  "%OUT%\api_request_inventory.csv"
  "%OUT%\determinism_rerun.json"
  "%OUT%\runtime_volume.json"
  "%OUT%\cache_inventory.json"
  "%OUT%\pilot_qa.md"
  "%OUT%\pilot_qa.json"
  "%OUT%\s2_pilot_manifest.json"
) do if not exist "%%~F" (
  echo FAIL: required STOPPUNKT B artifact is missing: %%~F
  goto :fail
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: datapilot changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo ========================================================================================
echo RAPSKARTAN SENTINEL-2 DATAPILOT RUNNER: PASS
echo ========================================================================================
echo No model, 2025 row-level test, Sentinel-1, full Skane, web or deployment ran.
echo Run next:
echo   VERIFY_RAPSKARTAN_S2_PILOT.bat "%OUT%"
echo.
echo STOPPUNKT B - return the complete logs and artifacts listed by the verifier.
exit /b 0

:fail
echo.
echo ========================================================================================
echo RAPSKARTAN SENTINEL-2 DATAPILOT RUNNER: FAIL OR BLOCKED
echo ========================================================================================
echo No model development or later phase ran.
echo If BLOCKED_CREDENTIALS is shown, set the two CDSE variables locally and rerun.
echo Never paste the client secret into chat or commit it to Git.
echo Return all files under: %OUT%\logs
exit /b 1
