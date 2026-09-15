@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_d2a_full_skane_split_discovery_v1"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo AkerPuls D2A - FULL-SKANE FROZEN B2 BASELINE SPLIT DISCOVERY - ZERO NETWORK
echo ========================================================================================
echo This stage runs B2 split discovery only. It does NOT run TRUE-LOO, history fusion or merge.
echo D2B remains blocked and requires separate authorization after this result is reviewed.
echo No S3/CDSE credentials are needed. Output: %OUT%
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
where py >nul 2>nul || (echo FAIL: Python launcher py is missing.& exit /b 1)
py -3 -c "import numpy,pandas,rasterio,geopandas,scipy,shapely" >nul 2>nul || (
  echo FAIL: required Python dependencies are missing.
  exit /b 1
)

if not exist "C:\AkerSyncRepo\work\akerpuls_d2_full_skane_model_plan_v1\d2_plan_manifest.json" (
  echo FAIL: D2 plan manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_d2_full_skane_model_plan_v1\D2_EXECUTION_CONTRACT.json" (
  echo FAIL: D2 execution contract missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_d2_full_skane_model_plan_v1\d2_cell_execution_plan.csv" (
  echo FAIL: D2 cell execution plan missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3j_full_skane_s3_acquisition_v1\d1s3j_vrt_outputs.csv" (
  echo FAIL: D1-S3j VRT index missing.
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
py -3 -m unittest tests.test_akerpuls_d2a_full_skane_split_discovery_v1 -v
if errorlevel 1 goto :fail

echo.
echo D2A starts now. This is local CPU/disk model execution over 46 cells.
echo It is resumable per cell; rerunning after interruption reuses hash-verified completed cell CSVs.
echo.
py -3 -u src\154_akerpuls_d2a_full_skane_split_discovery_v1.py --output-dir "%OUT%"
set "RC=%ERRORLEVEL%"

if not exist "%OUT%\d2a_manifest.json" (
  echo FAIL: d2a_manifest.json missing.
  goto :fail
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D2A changed Git-visible files.
  git status --short
  goto :fail
)

if "%RC%"=="0" goto :pass
if "%RC%"=="2" goto :review
goto :fail

:pass
echo.
echo ========================================================================================
echo STOPPUNKT D2A: COMPLETE - REVIEW SPLIT CENSUS BEFORE ANY D2B TRUE-LOO/FUSION
echo ========================================================================================
echo D2B remains unauthorized. Return the D2A summary to ChatGPT.
exit /b 0

:review
echo.
echo ========================================================================================
echo STOPPUNKT D2A: REVIEW - DO NOT RUN D2B
echo ========================================================================================
echo Return the D2A summary to ChatGPT. No network or Process PU was used.
exit /b 2

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D2A: FAIL OR BLOCKED
echo ========================================================================================
echo D2B remains blocked. This runner contains no network or Process API path.
exit /b 1
