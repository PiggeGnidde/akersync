@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "PILOT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c0_selection"
set "RASTERS=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c1_rasters"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c2_validation"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)
py -3 -c "import geopandas,numpy,pandas,rasterio,scipy,shapely" >nul 2>nul || (
  echo FAIL: Python dependencies missing.
  exit /b 1
)
if not exist "%RASTERS%\c1_manifest.json" (
  echo FAIL: C1 manifest missing.
  exit /b 1
)

echo ========================================================================================
echo AkerPuls 2026 - STOPPUNKT C2 LOCKED INDEPENDENT VALIDATION - ZERO PU
echo ========================================================================================
py -3 -m unittest tests.test_akerpuls_prelim_fields_2026_c2_contract -v
if errorlevel 1 exit /b 1
py -3 src\121_akerpuls_prelim_fields_2026_c2_locked_validation.py --pilot-dir "%PILOT%" --raster-dir "%RASTERS%" --output-dir "%OUT%"
exit /b %ERRORLEVEL%
