@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "PILOT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c5a_selection"
set "RASTERS=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c5b_rasters"
set "C5C=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c5c_validation"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c5d_blind_qa"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)

py -3 -c "import geopandas,numpy,pandas,rasterio,PIL,shapely" >nul 2>nul || (
  echo FAIL: Python dependencies missing from py -3 environment.
  exit /b 1
)

if not exist "%PILOT%\c5a_pilot_fields_2025.gpkg" (
  echo FAIL: C5a pilot missing.
  exit /b 1
)
if not exist "%RASTERS%\c5b_manifest.json" (
  echo FAIL: C5b raster manifest missing.
  exit /b 1
)
if not exist "%C5C%\c5c_field_validation.csv" (
  echo FAIL: C5c validation output missing.
  exit /b 1
)
if not exist "%C5C%\c5c_split_children.gpkg" (
  echo FAIL: C5c split-child geometry missing.
  exit /b 1
)

echo ========================================================================================
echo AkerPuls 2026 - STOPPUNKT C5D BLIND THIRD-HOLDOUT QA - ZERO PU
echo ========================================================================================

py -3 -m unittest -v tests.test_akerpuls_prelim_fields_2026_c5d_contract
if errorlevel 1 exit /b 1

py -3 src\128_akerpuls_prelim_fields_2026_c5d_blind_qa.py --pilot-dir "%PILOT%" --raster-dir "%RASTERS%" --c5c-dir "%C5C%" --output-dir "%OUT%"
exit /b %ERRORLEVEL%
