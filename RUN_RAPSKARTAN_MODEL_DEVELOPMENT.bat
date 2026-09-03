@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/rapskartan-skane-v1a"
set "RAW_ROOT=C:\AkerSyncRaw"
set "STOP_B=C:\AkerSyncRepo\work\rapskartan_skane_v1_s2_pilot_stopB"
set "OUT=C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC"
set "CACHE=C:\AkerSyncRaw\rapskartan_v1\sentinel2_l2a\model_development_v1"
if not "%~1"=="" set "RAW_ROOT=%~1"
if not "%~2"=="" set "OUT=%~2"
if not "%~3"=="" set "CACHE=%~3"
if not "%~4"=="" set "STOP_B=%~4"

echo ========================================================================================
echo Rapskartan Skane V1 - PRE-2025 MODEL DEVELOPMENT - STOPPUNKT C
echo ========================================================================================
echo Raw root:        %RAW_ROOT%
echo Accepted StopB: %STOP_B%
echo Output:          %OUT%
echo Content cache:   %CACHE%
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before model development.
  git status --short
  exit /b 1
)
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)
where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher 'py' is missing.
  exit /b 1
)
if "%CDSE_CLIENT_ID%"=="" (
  echo BLOCKED_CREDENTIALS: CDSE_CLIENT_ID is not set in this cmd.exe window.
  exit /b 1
)
if "%CDSE_CLIENT_SECRET%"=="" (
  echo BLOCKED_CREDENTIALS: CDSE_CLIENT_SECRET is not set in this cmd.exe window.
  exit /b 1
)
py -3 -c "import geopandas, joblib, matplotlib, numpy, pandas, shapely, sklearn" >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python needs geopandas, joblib, matplotlib, numpy, pandas, shapely and scikit-learn.
  exit /b 1
)
if not exist "%STOP_B%\s2_pilot_manifest.json" (
  echo FAIL: accepted STOPPUNKT B manifest is missing: %STOP_B%\s2_pilot_manifest.json
  exit /b 1
)
if not exist "%OUT%\logs" mkdir "%OUT%\logs"
if errorlevel 1 exit /b 1

echo [1/3] Leakage, dataset, model, calibration and prior tests...
py -3 -m unittest tests.test_rapskartan_v1_discovery tests.test_rapskartan_s2_pilot tests.test_rapskartan_model_dataset tests.test_rapskartan_model_training -v > "%OUT%\logs\model_tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\model_tests.log"
if not "%RC%"=="0" goto :fail

echo.
echo [2/3] Build deterministic pre-2025 dataset and Sentinel-2 cache...
echo Progress is shown every 50 fields. First run can take tens of minutes; reruns use cache.
powershell -NoProfile -Command "& { py -3 -u src\94_build_rapskartan_model_dataset.py --raw-root '%RAW_ROOT%' --stop-b-dir '%STOP_B%' --output-dir '%OUT%' --cache-root '%CACHE%' 2>&1 | Tee-Object -FilePath '%OUT%\logs\model_dataset.log'; exit $LASTEXITCODE }"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :fail

echo.
echo [3/3] Whole-year CV, calibration, thresholds and pre-blind freeze candidate...
powershell -NoProfile -Command "& { py -3 -u src\95_train_rapskartan_models.py --output-dir '%OUT%' 2>&1 | Tee-Object -FilePath '%OUT%\logs\model_training.log'; exit $LASTEXITCODE }"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :fail

for %%F in (
  "%OUT%\development_dataset_manifest.json"
  "%OUT%\rapskartan_model_contract_v1.json"
  "%OUT%\feature_contract_v1.json"
  "%OUT%\threshold_contract_v1.json"
  "%OUT%\calibration_contract_v1.json"
  "%OUT%\development_cv_results.json"
  "%OUT%\development_cv_by_cutoff.csv"
  "%OUT%\model_artifacts_manifest.json"
) do if not exist "%%~F" (
  echo FAIL: required STOPPUNKT C artifact is missing: %%~F
  goto :fail
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: model development changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo ========================================================================================
echo RAPSKARTAN MODEL DEVELOPMENT RUNNER: PASS
echo ========================================================================================
echo No 2025 label/prediction, Sentinel-1, full Skane, web, deployment, tag or merge ran.
echo Run next:
echo   VERIFY_RAPSKARTAN_MODEL_DEVELOPMENT.bat "%OUT%"
echo.
echo STOPPUNKT C - return the complete logs and artifacts listed by the verifier.
exit /b 0

:fail
echo.
echo ========================================================================================
echo RAPSKARTAN MODEL DEVELOPMENT RUNNER: FAIL OR BLOCKED
echo ========================================================================================
echo No 2025 blind prediction/evaluation or later phase ran.
echo Return every file under: %OUT%\logs
exit /b 1
