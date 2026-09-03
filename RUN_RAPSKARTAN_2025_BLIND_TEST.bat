@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/rapskartan-skane-v1a"
set "RAW_ROOT=C:\AkerSyncRaw"
set "STOP_C=C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC"
set "TRUTH_DIR=C:\AkerSyncRepo\work\akerscore_validation_csv_upload"
set "OUT=C:\AkerSyncRepo\work\rapskartan_skane_v1_blind_2025_stopD"
set "CACHE=C:\AkerSyncRaw\rapskartan_v1\sentinel2_l2a\blind_2025_benchmark_v1"
if not "%~1"=="" set "RAW_ROOT=%~1"
if not "%~2"=="" set "OUT=%~2"
if not "%~3"=="" set "CACHE=%~3"
if not "%~4"=="" set "STOP_C=%~4"
if not "%~5"=="" set "TRUTH_DIR=%~5"

echo ========================================================================================
echo Rapskartan Skane V1 - 2025 BLIND BENCHMARK - STOPPUNKT D
echo ========================================================================================
echo Raw root:       %RAW_ROOT%
echo Accepted StopC: %STOP_C%
echo Output:         %OUT%
echo Content cache: %CACHE%
echo Ground truth:  hidden from prediction process; opened only after SHA lock
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before the blind benchmark.
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
if not exist "%STOP_C%\model_artifacts_manifest.json" (
  echo FAIL: accepted STOPPUNKT C model manifest is missing.
  exit /b 1
)
if not exist "%TRUTH_DIR%\akerminne_2015_2025_selected.csv.gz" (
  echo FAIL: frozen ground-truth source is missing. It will not be opened before prediction lock.
  exit /b 1
)
if not exist "%OUT%\logs" mkdir "%OUT%\logs"
if errorlevel 1 exit /b 1

echo [1/3] Blind-gate, frozen-feature, prediction, evaluation and legacy contract tests...
py -3 -m unittest tests.test_rapskartan_v1_discovery tests.test_rapskartan_s2_pilot tests.test_rapskartan_model_dataset tests.test_rapskartan_model_training tests.test_rapskartan_2025_blind_prediction tests.test_rapskartan_2025_blind_evaluation -v > "%OUT%\logs\blind_tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\blind_tests.log"
if not "%RC%"=="0" goto :fail_prelock

echo.
echo [2/3] Label-free 2025 features and predictions, then immutable SHA lock...
echo Up to 3,300 field requests. First run can take 1-3 hours; reruns use the content cache.
powershell -NoProfile -Command "& { py -3 -u src\97_generate_rapskartan_2025_blind_predictions.py --raw-root '%RAW_ROOT%' --stop-c-dir '%STOP_C%' --output-dir '%OUT%' --cache-root '%CACHE%' 2>&1 | Tee-Object -FilePath '%OUT%\logs\blind_prediction.log'; exit $LASTEXITCODE }"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :fail_prelock
if not exist "%OUT%\prediction_lock_manifest.json" (
  echo FAIL: prediction lock was not created. Ground truth remains unopened.
  goto :fail_prelock
)

echo.
echo [3/3] Prediction lock recheck, then one-way opening of 2025 ground truth and evaluation...
powershell -NoProfile -Command "& { py -3 -u src\98_evaluate_rapskartan_2025_blind.py --ground-truth-dir '%TRUTH_DIR%' --output-dir '%OUT%' 2>&1 | Tee-Object -FilePath '%OUT%\logs\blind_evaluation.log'; exit $LASTEXITCODE }"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :fail_postlock
if not exist "%OUT%\blind_evaluation_manifest.json" (
  echo FAIL: blind evaluation manifest is missing.
  goto :fail_postlock
)
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: blind benchmark changed Git-visible files.
  git status --short
  goto :fail_postlock
)

echo.
echo ========================================================================================
echo RAPSKARTAN 2025 BLIND TEST RUNNER: PASS
echo ========================================================================================
echo Predictions were SHA-locked before 2025 ground truth was opened.
echo No model, feature, calibration or threshold tuning ran after unblind.
echo No full Skane prediction, Sentinel-1, web, deployment, tag or merge ran.
echo Run next:
echo   VERIFY_RAPSKARTAN_2025_BLIND_TEST.bat "%OUT%" "%STOP_C%" "%TRUTH_DIR%"
echo.
echo STOPPUNKT D - return the complete logs and artifacts listed by the verifier.
exit /b 0

:fail_prelock
echo.
echo RAPSKARTAN 2025 BLIND TEST RUNNER: FAIL OR BLOCKED BEFORE LABEL GATE
echo Ground-truth source was not opened by the prediction process.
echo Return every file under: %OUT%\logs
exit /b 1

:fail_postlock
echo.
echo RAPSKARTAN 2025 BLIND TEST RUNNER: FAIL AFTER PREDICTION LOCK
echo Predictions remain hash-locked; no tuning or later phase ran.
echo Return every file under: %OUT%\logs
exit /b 1
