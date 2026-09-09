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
set "B4=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b4_diagnostic"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b5_holdout"
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.& exit /b 1)
py -3 -c "import geopandas,numpy,pandas,rasterio,shapely,PIL" >nul 2>nul || (echo FAIL: Python dependencies missing.& exit /b 1)
if not exist "%B4%\b4_summary.json" (echo FAIL: B4 summary missing.& exit /b 1)
echo ========================================================================================
echo AkerPuls 2026 - STOPPUNKT B5 PROVISIONAL SPLIT RULE + HOLDOUT QA - ZERO PU
echo ========================================================================================
py -3 -m unittest tests.test_akerpuls_prelim_fields_2026_b5_holdout -v
if errorlevel 1 exit /b 1
py -3 src\117_akerpuls_prelim_fields_2026_b5_holdout.py --pilot-dir "%PILOT%" --raster-dir "%RASTERS%" --baseline-dir "%BASELINE%" --b3-dir "%B3%" --b4-dir "%B4%" --output-dir "%OUT%"
exit /b %ERRORLEVEL%
