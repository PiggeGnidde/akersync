@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_full_skane_d1_acquisition_v1"
set "RAW=C:\AkerSyncRaw\akerpuls_full_skane_split_fusion_qa_v1"
if not "%~1"=="" set "OUT=%~1"
if not "%~2"=="" set "RAW=%~2"

echo ========================================================================================
echo AkerPuls split fusion QA v1 - FULL SKANE D1 SENTINEL ACQUISITION
echo ========================================================================================
echo IMPORTANT: this stage may spend approximately 5535 Sentinel Hub PU.
echo It is resumable and does NOT alter field geometry.
echo Output: %OUT%
echo Raw:    %RAW%
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
if "%CDSE_CLIENT_ID%"=="" (echo BLOCKED_CREDENTIALS: CDSE_CLIENT_ID is not set.& exit /b 1)
if "%CDSE_CLIENT_SECRET%"=="" (echo BLOCKED_CREDENTIALS: CDSE_CLIENT_SECRET is not set.& exit /b 1)
if not exist "C:\AkerSyncRepo\work\akerpuls_full_skane_d0b_sparse_norm_v1\D1_EXECUTION_CONTRACT_FINAL.json" (
  echo FAIL: final D0b execution contract missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_full_skane_d0_plan_v1\d0_process_request_plan.csv" (
  echo FAIL: D0 request plan missing.
  exit /b 1
)
py -3 -c "import numpy,pandas,rasterio" >nul 2>nul || (
  echo FAIL: required Python dependencies numpy/pandas/rasterio are missing.
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"

py -3 -m unittest tests.test_akerpuls_full_skane_d1_acquisition_v1 -v
if errorlevel 1 goto :fail

echo.
echo D1 starts now. Expect hundreds of Process API requests; progress prints every 10 requests.
echo Safe to rerun after interruption: verified daily tiles are reused from cache.
echo.
py -3 -u src\140_akerpuls_full_skane_d1_acquisition_v1.py --output-dir "%OUT%" --raw-root "%RAW%"
if errorlevel 1 goto :fail

if not exist "%OUT%\d1_manifest.json" (echo FAIL: d1_manifest.json missing.& goto :fail)
if not exist "%OUT%\d1_api_requests.csv" (echo FAIL: d1_api_requests.csv missing.& goto :fail)
if not exist "%OUT%\d1_snapshot_tiles.csv" (echo FAIL: d1_snapshot_tiles.csv missing.& goto :fail)
if not exist "%OUT%\d1_vrts.csv" (echo FAIL: d1_vrts.csv missing.& goto :fail)

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D1 changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo ========================================================================================
echo STOPPUNKT D1: PASS - SENTINEL ACQUISITION COMPLETE
 echo ========================================================================================
echo Return the final D1 console summary to ChatGPT before D2 model application.
exit /b 0

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D1: FAIL OR INTERRUPTED
 echo ========================================================================================
echo Existing verified daily downloads are retained and can be resumed by rerunning this BAT.
exit /b 1
