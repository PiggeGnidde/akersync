@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_d2_full_skane_model_plan_v1"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo AkerPuls D2 - FULL-SKANE MODEL PLAN ONLY - ZERO NETWORK / ZERO MODEL EXECUTION
echo ========================================================================================
echo Prerequisite: D1-S3k PASS_TO_FULL_SKANE_D2_MODEL_PLAN.
echo This stage only freezes the 46-cell execution plan and D2A/D2B stopping-point contract.
echo It does NOT run B2 discovery, TRUE-LOO, fusion, STAC, S3 or Sentinel Hub Process.
echo Output: %OUT%
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
py -3 -c "import numpy,pandas" >nul 2>nul || (
  echo FAIL: numpy/pandas missing.
  exit /b 1
)

if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3k_full_skane_raster_qa_v1\d1s3k_manifest.json" (
  echo FAIL: D1-S3k manifest missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_d1s3k_full_skane_raster_qa_v1\d1s3k_field_validity.csv" (
  echo FAIL: D1-S3k field validity missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_full_skane_d0b_sparse_norm_v1\D1_EXECUTION_CONTRACT_FINAL.json" (
  echo FAIL: D0b execution contract missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_full_skane_d0b_sparse_norm_v1\d0b_resolved_normalization_windows.csv" (
  echo FAIL: D0b resolved normalization windows missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_geometry_rolling_backtest_v0\field_prior_2026_preview.csv" (
  echo FAIL: rolling 2026 field prior missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_fusion_freeze_c7a_v0\FUSION_SCORE_FREEZE_BEFORE_C7.json" (
  echo FAIL: frozen fusion artifact missing.
  exit /b 1
)

if not exist "%OUT%" mkdir "%OUT%"
py -3 -m unittest tests.test_akerpuls_d2_full_skane_model_plan_v1 -v
if errorlevel 1 goto :fail

echo.
echo D2 plan starts now. Local metadata/CSV audit only; no model execution.
echo.
py -3 -u src\153_akerpuls_d2_full_skane_model_plan_v1.py --output-dir "%OUT%"
set "RC=%ERRORLEVEL%"

if not exist "%OUT%\d2_plan_manifest.json" (
  echo FAIL: d2_plan_manifest.json missing.
  goto :fail
)
if not exist "%OUT%\D2_EXECUTION_CONTRACT.json" (
  echo FAIL: D2_EXECUTION_CONTRACT.json missing.
  goto :fail
)
if not exist "%OUT%\d2_cell_execution_plan.csv" (
  echo FAIL: d2_cell_execution_plan.csv missing.
  goto :fail
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D2 plan changed Git-visible files.
  git status --short
  goto :fail
)

if "%RC%"=="0" goto :pass
if "%RC%"=="2" goto :review
goto :fail

:pass
echo.
echo ========================================================================================
echo STOPPUNKT D2 PLAN: PASS - D2A BASELINE SPLIT DISCOVERY MAY BE BUILT NEXT
 echo ========================================================================================
echo No model was executed. D2B TRUE-LOO/fusion remains separately blocked until D2A review.
exit /b 0

:review
echo.
echo ========================================================================================
echo STOPPUNKT D2 PLAN: REVIEW - DO NOT BUILD OR RUN D2A YET
 echo ========================================================================================
echo Return the plan summary to ChatGPT.
exit /b 2

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D2 PLAN: FAIL OR BLOCKED
 echo ========================================================================================
echo This stage has no network or model-execution path.
exit /b 1
