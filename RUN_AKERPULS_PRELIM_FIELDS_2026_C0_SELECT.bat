@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c0_selection"
set "LOCAL_PATHS=%CD%\config\local_paths.json"
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.& exit /b 1)
py -3 -c "import geopandas,pandas,shapely" >nul 2>nul || (echo FAIL: Python dependencies missing.& exit /b 1)
echo ========================================================================================
echo AkerPuls 2026 - STOPPUNKT C0 INDEPENDENT GEOGRAPHIC PILOT - ZERO PU
echo ========================================================================================
py -3 src\119_akerpuls_prelim_fields_2026_c0_select.py --local-paths "%LOCAL_PATHS%" --output-dir "%OUT%"
exit /b %ERRORLEVEL%
