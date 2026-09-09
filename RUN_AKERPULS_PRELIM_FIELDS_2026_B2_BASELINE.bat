@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "PILOT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_stopb0_selection"
set "RASTERS=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b1_rasters"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b2_baseline"
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.& exit /b 1)
py -3 -c "import geopandas,numpy,pandas,rasterio,scipy,shapely" >nul 2>nul || (echo FAIL: Python dependencies missing.& exit /b 1)
if not exist "%RASTERS%\b1_manifest.json" (echo FAIL: B1 manifest missing.& exit /b 1)
echo ========================================================================================
echo AkerPuls 2026 - STOPPUNKT B2 LOCAL SPLIT/MERGE BASELINE - ZERO PU
echo ========================================================================================
py -3 -m unittest tests.test_akerpuls_prelim_fields_2026_b2_baseline -v
if errorlevel 1 exit /b 1
py -3 src\113_akerpuls_prelim_fields_2026_b2_baseline.py --pilot-dir "%PILOT%" --raster-dir "%RASTERS%" --output-dir "%OUT%"
exit /b %ERRORLEVEL%
