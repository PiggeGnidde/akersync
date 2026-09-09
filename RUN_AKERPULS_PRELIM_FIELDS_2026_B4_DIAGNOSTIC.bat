@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "PILOT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_stopb0_selection"
set "RASTERS=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b1_rasters"
set "BASELINE=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b2_baseline"
set "B3=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b3_qa"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b4_diagnostic"
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.& exit /b 1)
py -3 -c "import geopandas,numpy,pandas,rasterio,scipy,shapely" >nul 2>nul || (echo FAIL: Python dependencies missing.& exit /b 1)
if not exist "%B3%\b3_summary.json" (echo FAIL: B3 summary missing.& exit /b 1)
echo ========================================================================================
echo AkerPuls 2026 - STOPPUNKT B4 MORPHOLOGY + EDGE SENSITIVITY - ZERO PU
echo ========================================================================================
py -3 -m unittest tests.test_akerpuls_prelim_fields_2026_b4_diagnostic -v
if errorlevel 1 exit /b 1
py -3 src\115_akerpuls_prelim_fields_2026_b4_diagnostic.py --pilot-dir "%PILOT%" --raster-dir "%RASTERS%" --baseline-dir "%BASELINE%" --b3-dir "%B3%" --output-dir "%OUT%"
exit /b %ERRORLEVEL%
