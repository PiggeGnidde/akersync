@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "D2C=C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1"
if not "%~1"=="" set "D2C=%~1"

echo ========================================================================================
echo AkerPuls D2C - POST-FREEZE SATELLITE REVIEW MAP - VISUALIZATION ONLY
echo ========================================================================================
echo This creates a NEW HTML map with Esri World Imagery as the default basemap.
echo It does not rewrite the frozen D2C map, ranking, freeze, thresholds, sample, or geometry.
echo Python performs no network calls. The browser requests map tiles only when HTML is opened.
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean.
  git status --short
  exit /b 1
)
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)
where py >nul 2>nul || (echo FAIL: Python launcher py is missing.& exit /b 1)

if not exist "%D2C%\d2c_manifest.json" (
  echo FAIL: frozen D2C manifest missing.
  exit /b 1
)
if not exist "%D2C%\D2C_FULL_SKANE_QA_RANKING_FREEZE_V1.json" (
  echo FAIL: frozen D2C freeze file missing.
  exit /b 1
)
if not exist "%D2C%\d2c_review_p90plus_wgs84.geojson" (
  echo FAIL: frozen D2C P90+ GeoJSON missing.
  exit /b 1
)

py -3 -m unittest tests.test_akerpuls_d2c_review_satellite_map_v1 -v
if errorlevel 1 goto :fail

echo.
py -3 -u src\157_akerpuls_d2c_review_satellite_map_v1.py --d2c-dir "%D2C%"
if errorlevel 1 goto :fail

if not exist "%D2C%\d2c_review_p90plus_satellite_map.html" (
  echo FAIL: satellite review HTML missing.
  goto :fail
)
if not exist "%D2C%\d2c_review_p90plus_satellite_map_manifest.json" (
  echo FAIL: satellite review map manifest missing.
  goto :fail
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: post-freeze visualization changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo ========================================================================================
echo PASS - OPEN THE NEW SATELLITE REVIEW MAP
echo ========================================================================================
echo %D2C%\d2c_review_p90plus_satellite_map.html
echo.
echo The original frozen d2c_review_p90plus_map.html is intentionally unchanged.
exit /b 0

:fail
echo.
echo ========================================================================================
echo FAIL - D2C FROZEN ARTIFACTS WERE NOT TOUCHED
 echo ========================================================================================
exit /b 1
