@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
set "MAP_RAW=C:\AkerSyncRaw"
set "MAP_OUT=%~dp0data\derived\rapskartan_v1\2025_map_product_v3"
set "MAP_ARCHIVE=C:\AkerSyncRaw\rapskartan_v1\sentinel2_l2a\map_product_2025_scene_archive_v1"
set "MAP_STOP_C=C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC"
set "MAP_STOP_D=C:\AkerSyncRepo\work\rapskartan_skane_v1_blind_2025_stopD"
if not "%~1"=="" set "MAP_RAW=%~1"
if not "%~2"=="" set "MAP_OUT=%~2"
if not "%~3"=="" set "MAP_ARCHIVE=%~3"
if not "%~4"=="" set "MAP_STOP_C=%~4"
if not "%~5"=="" set "MAP_STOP_D=%~5"
echo RAPSKARTAN FULL MAP - ACCEPTED V3 ENGINE - OFFLINE ONLY
echo No credentials or downloads. Existing original and diagnostic caches remain separate.
echo Output: %MAP_OUT%
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree must be clean.
  exit /b 1
)
for /f "delims=" %%B in ('git branch --show-current') do set "MAP_BRANCH=%%B"
if /I not "%MAP_BRANCH%"=="feature/rapskartan-skane-v1a" (
  echo FAIL: expected feature/rapskartan-skane-v1a.
  exit /b 1
)
if not exist "%MAP_OUT%\logs" mkdir "%MAP_OUT%\logs"
if errorlevel 1 exit /b 1
echo [1/3] Full regression and adopted-engine restart/safety tests...
py -3 -m unittest tests.test_rapskartan_v1_discovery tests.test_rapskartan_s2_pilot tests.test_rapskartan_model_dataset tests.test_rapskartan_model_training tests.test_rapskartan_2025_blind_prediction tests.test_rapskartan_2025_blind_evaluation tests.test_rapskartan_map_product tests.test_rapskartan_parity_diagnostic tests.test_rapskartan_pixel_cases tests.test_rapskartan_pixel_reference tests.test_rapskartan_local_candidate tests.test_rapskartan_scene_choices tests.test_rapskartan_scene_order_candidate tests.test_rapskartan_adopted_engine -q > "%MAP_OUT%\logs\map_product_tests.log" 2>&1
set "MAP_RC=%ERRORLEVEL%"
type "%MAP_OUT%\logs\map_product_tests.log"
if not "%MAP_RC%"=="0" goto :fail
echo [2/3] Verify accepted evidence and archive; replay parity; generate restartable municipality/date shards...
echo Full pixel processing may take a long time. Completed dates survive interruption.
py -3 -u src\100_generate_rapskartan_2025_map_product.py --raw-root "%MAP_RAW%" --stop-c-dir "%MAP_STOP_C%" --stop-d-dir "%MAP_STOP_D%" --output-dir "%MAP_OUT%" --scene-archive "%MAP_ARCHIVE%"
if errorlevel 1 goto :fail
echo [3/3] Independent STOPPUNKT E verifier and return ZIP...
call VERIFY_RAPSKARTAN_2025_MAP_PRODUCT.bat "%MAP_OUT%" "%MAP_STOP_C%" "%MAP_STOP_D%"
if errorlevel 1 goto :fail
echo Full map completed and independently verified. STOPPUNKT E - no web or deployment.
exit /b 0
:fail
echo RAPSKARTAN FULL MAP: FAIL OR BLOCKED. No web, Sentinel-1, deployment, tag or merge ran.
echo Keep all caches. Return the error above and logs under: %MAP_OUT%\logs
exit /b 1
