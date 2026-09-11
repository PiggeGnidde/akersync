@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
if not defined AKERMINNE_WORKSPACE set "AKERMINNE_WORKSPACE=C:\AkerSync-Minne"
set "OUT=C:\AkerSyncRepo\work\akerpuls_geometry_rolling_backtest_v0"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)

where py >nul 2>nul || (
  echo FAIL: Python launcher py is missing.
  exit /b 1
)

py -3 -c "import numpy,pandas,pyarrow,geopandas,shapely" >nul 2>nul || (
  echo FAIL: required Python packages numpy/pandas/pyarrow/geopandas/shapely are missing in py -3.
  exit /b 1
)

if not exist "%AKERMINNE_WORKSPACE%\config" (
  echo FAIL: AkerMinne workspace not found:
  echo   %AKERMINNE_WORKSPACE%
  echo Override with: set "AKERMINNE_WORKSPACE=C:\path\to\AkerSync-Minne"
  exit /b 1
)

if not exist "%AKERMINNE_WORKSPACE%\data\derived\akerminne_v1a\skane\skane_plan.json" (
  echo FAIL: frozen AkerMinne Skane plan not found in workspace.
  exit /b 1
)

echo ========================================================================================
echo AkerPuls 2026 - TRUE ROLLING GEOMETRY PRIOR BACKTEST - ZERO PU
 echo ========================================================================================
echo AKERMINNE_WORKSPACE=%AKERMINNE_WORKSPACE%
echo OUTPUT=%OUT%
echo.
echo This uses frozen local annual geometries only. No download and no Sentinel calls.
echo First run builds reusable adjacent-year transition caches and can take some time.
echo.

py -3 -m unittest tests.test_akerpuls_geometry_rolling_backtest -v
if errorlevel 1 exit /b 1

py -3 src\130_akerpuls_geometry_rolling_backtest.py --workspace "%AKERMINNE_WORKSPACE%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

endlocal
