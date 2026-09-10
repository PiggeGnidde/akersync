@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "PILOT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c5a_selection"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c5b_rasters"

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
if not exist "%PILOT%\c5a_pilot_fields_2025.gpkg" (
  echo FAIL: C5a pilot missing.
  exit /b 1
)

 echo ========================================================================================
 echo AkerPuls 2026 - STOPPUNKT C5B THIRD HOLDOUT 10m RASTER - FROZEN TEST RULES
 echo ========================================================================================
py -3 -m unittest tests.test_akerpuls_prelim_fields_2026_c5b_contract -v
if errorlevel 1 exit /b 1
py -3 src\126_akerpuls_prelim_fields_2026_c5b_rasters.py --pilot-dir "%PILOT%" --output-dir "%OUT%"
exit /b %ERRORLEVEL%
