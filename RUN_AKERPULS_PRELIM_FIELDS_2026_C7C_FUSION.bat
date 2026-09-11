@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c7c_fusion_validation"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)

py -3 -c "import numpy,pandas,scipy,geopandas,rasterio,shapely" >nul 2>nul || (
  echo FAIL: required Python dependencies are missing in py -3 environment.
  exit /b 1
)

if not exist "C:\AkerSyncRepo\work\akerpuls_fusion_freeze_c7a_v0\c7a_pilot_fields_2025.gpkg" (
  echo FAIL: C7A pilot missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c7b_rasters\c7b_manifest.json" (
  echo FAIL: C7B raster manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_fusion_freeze_c7a_v0\FUSION_SCORE_FREEZE_BEFORE_C7.json" (
  echo FAIL: frozen fusion artifact missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_geometry_rolling_backtest_v0\field_prior_2026_preview.csv" (
  echo FAIL: rolling prior preview missing.
  exit /b 1
)

echo ========================================================================================
echo AkerPuls 2026 - C7C FOURTH HOLDOUT FROZEN FUSION VALIDATION - ZERO PU
echo ========================================================================================

py -3 -m unittest tests.test_akerpuls_c7c_frozen_fusion_validation -v
if errorlevel 1 exit /b 1

py -3 src\135_akerpuls_c7c_frozen_fusion_validation.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

endlocal
