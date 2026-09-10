@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c5a_selection"
set "LOCAL_PATHS=%CD%\config\local_paths.json"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)
py -3 -c "import geopandas,pandas,shapely" >nul 2>nul || (
  echo FAIL: Python dependencies missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_stopb0_selection\pilot_fields_2025.gpkg" (
  echo FAIL: B pilot geometry missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c0_selection\c0_pilot_fields_2025.gpkg" (
  echo FAIL: C pilot geometry missing.
  exit /b 1
)

echo ========================================================================================
echo AkerPuls 2026 - STOPPUNKT C5A THIRD GEOGRAPHIC HOLDOUT SELECTION - ZERO PU
echo ========================================================================================
py -3 -m unittest tests.test_akerpuls_prelim_fields_2026_c5a_contract -v
if errorlevel 1 exit /b 1
py -3 src\125_akerpuls_prelim_fields_2026_c5a_select.py --local-paths "%LOCAL_PATHS%" --output-dir "%OUT%"
exit /b %ERRORLEVEL%
