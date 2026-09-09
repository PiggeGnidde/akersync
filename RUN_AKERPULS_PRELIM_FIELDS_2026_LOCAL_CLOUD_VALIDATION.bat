@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "COVERAGE=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_coverage_diag"
set "RESCUE=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_rescue_dates"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_local_cloud"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)
if "%CDSE_CLIENT_ID%"=="" (echo BLOCKED_CREDENTIALS: CDSE_CLIENT_ID is not set.& exit /b 1)
if "%CDSE_CLIENT_SECRET%"=="" (echo BLOCKED_CREDENTIALS: CDSE_CLIENT_SECRET is not set.& exit /b 1)
py -3 -c "import geopandas,pandas,shapely" >nul 2>nul || (echo FAIL: Python needs geopandas pandas shapely.& exit /b 1)

echo ========================================================================================
echo AkerPuls 2026 - LOCAL CLOUD VALIDATION - LOW PU
echo ========================================================================================
py -3 src\109_akerpuls_prelim_fields_2026_local_cloud_validation.py --coverage-dir "%COVERAGE%" --rescue-dir "%RESCUE%" --output-dir "%OUT%"
exit /b %ERRORLEVEL%
