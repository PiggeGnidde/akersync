@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_d2c_full_skane_freeze_review_v1"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo AkerPuls D2C - FREEZE FULL-SKANE QA RANKING + BUILD REVIEW PRODUCTS - ZERO NETWORK
echo ========================================================================================
echo Explicit post-D2B authorization: GO D2C.
echo Freezes the exact D2B ranking and joins unchanged official 2025 field polygons for review.
echo Builds full candidate GPKG, P90+/P95 review files, HTML map, and deterministic 100-field audit sample.
echo No model execution, threshold tuning, fusion refit, split-line generation, merge or geometry mutation.
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
py -3 -c "import numpy,pandas,geopandas,shapely" >nul 2>nul || (
  echo FAIL: required Python dependencies are missing.
  exit /b 1
)

if not exist "C:\AkerSyncRepo\work\akerpuls_d2b_full_skane_true_loo_fusion_v1\d2b_manifest.json" (
  echo FAIL: D2B manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_d2b_full_skane_true_loo_fusion_v1\d2b_fusion_candidates.csv" (
  echo FAIL: D2B frozen ranking CSV missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_d2b_full_skane_true_loo_fusion_v1\d2b_true_loo_candidates.csv" (
  echo FAIL: D2B TRUE-LOO CSV missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_fusion_freeze_c7a_v0\FUSION_SCORE_FREEZE_BEFORE_C7.json" (
  echo FAIL: frozen C7A fusion artifact missing.
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
py -3 -m unittest tests.test_akerpuls_d2c_full_skane_freeze_review_v1 -v
if errorlevel 1 goto :fail

echo.
echo D2C starts now. This is local freeze/packaging work only; it does not rerun D2B.
echo.
py -3 -u src\156_akerpuls_d2c_full_skane_freeze_review_v1.py --output-dir "%OUT%"
set "RC=%ERRORLEVEL%"

if not exist "%OUT%\d2c_manifest.json" (
  echo FAIL: d2c_manifest.json missing.
  goto :fail
)
if not exist "%OUT%\D2C_FULL_SKANE_QA_RANKING_FREEZE_V1.json" (
  echo FAIL: formal D2C freeze file missing.
  goto :fail
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D2C changed Git-visible files.
  git status --short
  goto :fail
)

if "%RC%"=="0" goto :pass
if "%RC%"=="2" goto :review
goto :fail

:pass
echo.
echo ========================================================================================
echo STOPPUNKT D2C: FROZEN - FULL-SKANE QA RANKING V1 + REVIEW PRODUCTS COMPLETE
echo ========================================================================================
echo Review the 100-field audit sample and P90+/P95 map before any split-line/geometric work.
echo Return the D2C summary to ChatGPT.
exit /b 0

:review
echo.
echo ========================================================================================
echo STOPPUNKT D2C: REVIEW - DO NOT START SPLIT-LINE OR GEOMETRY WORK
 echo ========================================================================================
echo Return the D2C summary to ChatGPT.
exit /b 2

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D2C: FAIL OR BLOCKED
 echo ========================================================================================
echo D2C contains no model, network, split-line or geometry-replacement execution path.
exit /b 1
