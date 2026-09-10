@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "PILOT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c0_selection"
set "RASTERS=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c1_rasters"
set "C2=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c2_validation"
set "C3=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c3_qa"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c4_high_confidence"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)

py -3 -c "import geopandas,numpy,pandas,rasterio,scipy,shapely" >nul 2>nul || (
  echo FAIL: Python dependencies missing.
  exit /b 1
)

if not exist "%C2%\c2_summary.json" (
  echo FAIL: C2 summary missing.
  exit /b 1
)
if not exist "%C3%\c3_BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv" (
  echo FAIL: C3 revealed blind key missing.
  exit /b 1
)

echo ========================================================================================
echo AkerPuls 2026 - STOPPUNKT C4 RICH TOPOLOGY + HIGH-CONFIDENCE DIAGNOSTIC - ZERO PU
echo ========================================================================================
py -3 -m unittest tests.test_akerpuls_prelim_fields_2026_c4_diagnostic -v
if errorlevel 1 exit /b 1

py -3 src\124_akerpuls_prelim_fields_2026_c4_high_confidence_diagnostic.py --pilot-dir "%PILOT%" --raster-dir "%RASTERS%" --c2-dir "%C2%" --c3-dir "%C3%" --output-dir "%OUT%"
exit /b %ERRORLEVEL%
