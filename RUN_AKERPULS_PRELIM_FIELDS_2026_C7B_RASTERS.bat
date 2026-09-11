@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "PILOT=C:\AkerSyncRepo\work\akerpuls_fusion_freeze_c7a_v0"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c7b_rasters"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)
if "%CDSE_CLIENT_ID%"=="" (echo BLOCKED_CREDENTIALS: CDSE_CLIENT_ID is not set.& exit /b 1)
if "%CDSE_CLIENT_SECRET%"=="" (echo BLOCKED_CREDENTIALS: CDSE_CLIENT_SECRET is not set.& exit /b 1)
py -3 -c "import geopandas,numpy,pandas,rasterio,shapely,PIL" >nul 2>nul || (
  echo FAIL: Python dependencies missing.
  exit /b 1
)
if not exist "%PILOT%\c7a_pilot_fields_2025.gpkg" (
  echo FAIL: C7A pilot missing.
  exit /b 1
)
if not exist "%PILOT%\FUSION_SCORE_FREEZE_BEFORE_C7.json" (
  echo FAIL: C7A fusion freeze missing.
  exit /b 1
)

echo ========================================================================================
echo AkerPuls 2026 - STOPPUNKT C7B FOURTH HOLDOUT 10m RASTER - HASH-PINNED FUSION FREEZE
echo ========================================================================================
py -3 -m unittest tests.test_akerpuls_prelim_fields_2026_c7b_contract -v
if errorlevel 1 exit /b 1
py -3 src\135_akerpuls_prelim_fields_2026_c7b_rasters.py --pilot-dir "%PILOT%" --output-dir "%OUT%"
exit /b %ERRORLEVEL%
