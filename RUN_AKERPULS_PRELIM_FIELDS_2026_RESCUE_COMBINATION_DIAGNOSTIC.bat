@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "LOCALCLOUD=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_local_cloud"
set "RESCUE=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_rescue_dates"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_combo_diag"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)
py -3 -c "import pandas" >nul 2>nul || (echo FAIL: Python needs pandas.& exit /b 1)

echo ========================================================================================
echo AkerPuls 2026 - RESCUE COMBINATION DIAGNOSTIC - ZERO PU
echo ========================================================================================
py -3 src\110_akerpuls_prelim_fields_2026_rescue_combination_diagnostic.py --local-cloud-dir "%LOCALCLOUD%" --rescue-dir "%RESCUE%" --output-dir "%OUT%"
exit /b %ERRORLEVEL%
