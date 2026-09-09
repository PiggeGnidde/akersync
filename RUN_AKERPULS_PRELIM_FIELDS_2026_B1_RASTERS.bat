@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "PILOT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_stopb0_selection"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b1_rasters"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)
if "%CDSE_CLIENT_ID%"=="" (echo BLOCKED_CREDENTIALS: CDSE_CLIENT_ID is not set.& exit /b 1)
if "%CDSE_CLIENT_SECRET%"=="" (echo BLOCKED_CREDENTIALS: CDSE_CLIENT_SECRET is not set.& exit /b 1)
py -3 -c "import geopandas,numpy,pandas,rasterio,shapely,PIL" >nul 2>nul || (
  echo FAIL: Python needs geopandas numpy pandas rasterio shapely Pillow.
  exit /b 1
)
if not exist "%PILOT%\pilot_fields_2025.gpkg" (
  echo FAIL: missing B0 pilot %PILOT%\pilot_fields_2025.gpkg
  exit /b 1
)

echo ========================================================================================
echo AkerPuls 2026 - STOPPUNKT B1 BOUNDED 10m RASTER PILOT
echo ========================================================================================
py -3 src\112_akerpuls_prelim_fields_2026_b1_rasters.py --pilot-dir "%PILOT%" --output-dir "%OUT%"
exit /b %ERRORLEVEL%
