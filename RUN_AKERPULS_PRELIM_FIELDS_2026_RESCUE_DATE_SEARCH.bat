@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "COVERAGE=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_coverage_diag"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_rescue_dates"
if not "%~1"=="" set "COVERAGE=%~1"
if not "%~2"=="" set "OUT=%~2"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)

py -3 -c "import geopandas,shapely" >nul 2>nul || (
  echo FAIL: Python needs geopandas and shapely.
  exit /b 1
)

echo ========================================================================================
echo AkerPuls 2026 - RESCUE DATE SEARCH - PUBLIC STAC ONLY - ZERO PU
echo ========================================================================================
py -3 src\108_akerpuls_prelim_fields_2026_rescue_date_search.py --coverage-dir "%COVERAGE%" --output-dir "%OUT%"
exit /b %ERRORLEVEL%
