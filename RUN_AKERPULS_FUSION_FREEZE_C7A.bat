@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_fusion_freeze_c7a_v0"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)

where py >nul 2>nul || (
  echo FAIL: Python launcher py is missing.
  exit /b 1
)

py -3 -c "import numpy,pandas,geopandas,shapely" >nul 2>nul || (
  echo FAIL: required Python dependencies are missing in py -3 environment.
  exit /b 1
)

if not exist "C:\AkerSyncRepo\work\akerpuls_true_loo_diagnostic_v0\true_loo_candidates_all.csv" (
  echo FAIL: combined TRUE-LOO candidate output missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_geometry_rolling_backtest_v0\field_prior_2026_preview.csv" (
  echo FAIL: rolling prior preview missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c5a_selection\c5a_pilot_fields_2025.gpkg" (
  echo FAIL: C5A prior holdout geometry missing.
  exit /b 1
)

echo ========================================================================================
echo AkerPuls 2026 - C7A LABEL-FREE FUSION FREEZE + FOURTH GEOGRAPHIC HOLDOUT - ZERO PU
echo ========================================================================================

py -3 -m unittest tests.test_akerpuls_fusion_freeze_c7a -v
if errorlevel 1 exit /b 1

py -3 src\135_akerpuls_fusion_freeze_c7a_runner.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

endlocal
