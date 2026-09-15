@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_d2b_full_skane_true_loo_fusion_v1"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo AkerPuls D2B - FULL-SKANE TRUE-LOO + FROZEN 3-SIGNAL QA FUSION - ZERO NETWORK
echo ========================================================================================
echo Explicit post-D2A authorization: GO D2B.
echo Scope: TRUE-LOO on the 12,676 D2A split candidates, rolling prior lookup, frozen fusion.
echo No STAC, S3, Process API, merge, threshold tuning, fusion refit or geometry replacement.
echo This run is resumable per analysis cell and MUST stop for review when complete.
echo No S3/CDSE credentials are needed. Output: %OUT%
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
py -3 -c "import numpy,pandas,rasterio,geopandas,scipy,shapely" >nul 2>nul || (
  echo FAIL: required Python dependencies are missing.
  exit /b 1
)

if not exist "C:\AkerSyncRepo\work\akerpuls_d2a_full_skane_split_discovery_v1\d2a_manifest.json" (
  echo FAIL: D2A manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_d2a_full_skane_split_discovery_v1\d2a_field_split_discovery.csv" (
  echo FAIL: D2A field split discovery missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_d2_full_skane_model_plan_v1\D2_EXECUTION_CONTRACT.json" (
  echo FAIL: D2 execution contract missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_fusion_freeze_c7a_v0\FUSION_SCORE_FREEZE_BEFORE_C7.json" (
  echo FAIL: frozen fusion artifact missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_geometry_rolling_backtest_v0\field_prior_2026_preview.csv" (
  echo FAIL: frozen rolling prior missing.
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
py -3 -m unittest tests.test_akerpuls_d2b_full_skane_true_loo_fusion_v1 -v
if errorlevel 1 goto :fail

echo.
echo D2B starts now. This is the expensive local TRUE-LOO stage: about 50,704 omission refits.
echo Completed cell TRUE-LOO outputs are hash-verified and reused after interruption.
echo.
py -3 -u src\155_akerpuls_d2b_full_skane_true_loo_fusion_v1.py --output-dir "%OUT%"
set "RC=%ERRORLEVEL%"

if not exist "%OUT%\d2b_manifest.json" (
  echo FAIL: d2b_manifest.json missing.
  goto :fail
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D2B changed Git-visible files.
  git status --short
  goto :fail
)

if "%RC%"=="0" goto :pass
if "%RC%"=="2" goto :review
goto :fail

:pass
echo.
echo ========================================================================================
echo STOPPUNKT D2B: COMPLETE - REVIEW FULL-SKANE TRUE-LOO/FUSION RANKING
 echo ========================================================================================
echo No geometry mutation is authorized. Return the D2B summary to ChatGPT.
exit /b 0

:review
echo.
echo ========================================================================================
echo STOPPUNKT D2B: REVIEW - DO NOT MUTATE GEOMETRY
 echo ========================================================================================
echo Return the D2B summary to ChatGPT. No network or Sentinel Hub PU was used.
exit /b 2

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D2B: FAIL OR BLOCKED
 echo ========================================================================================
echo This runner contains no network, Process API or automatic geometry-replacement path.
exit /b 1
