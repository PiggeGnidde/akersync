@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "OUT=C:\AkerSyncRepo\work\rapskartan_skane_v1_blind_2025_stopD"
set "STOP_C=C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC"
set "TRUTH_DIR=C:\AkerSyncRepo\work\akerscore_validation_csv_upload"
if not "%~1"=="" set "OUT=%~1"
if not "%~2"=="" set "STOP_C=%~2"
if not "%~3"=="" set "TRUTH_DIR=%~3"

echo ========================================================================================
echo Rapskartan Skane V1 - INDEPENDENT 2025 BLIND VERIFIER - STOPPUNKT D
echo ========================================================================================
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before verification.
  git status --short
  exit /b 1
)
where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher 'py' is missing.
  exit /b 1
)
py -3 -c "import joblib, numpy, pandas, sklearn" >nul 2>nul
if errorlevel 1 (
  echo FAIL: verifier needs joblib, numpy, pandas and scikit-learn.
  exit /b 1
)
if not exist "%OUT%\logs" mkdir "%OUT%\logs"
py -3 src\99_verify_rapskartan_2025_blind.py --output-dir "%OUT%" --stop-c-dir "%STOP_C%" --ground-truth-dir "%TRUTH_DIR%" > "%OUT%\logs\stopd_verify.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\stopd_verify.log"
if not "%RC%"=="0" goto :fail
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: verifier changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo VERIFY_RAPSKARTAN_2025_BLIND_TEST: PASS
echo STOPPUNKT D - do not run full Skane prediction, web, Sentinel-1, tag, merge or deployment without explicit GO.
echo.
echo Return:
echo   1. %OUT%\logs\blind_tests.log
echo   2. %OUT%\logs\blind_prediction.log
echo   3. %OUT%\logs\blind_evaluation.log
echo   4. %OUT%\logs\stopd_verify.log
echo   5. %OUT%\prediction_lock_manifest.json
echo   6. %OUT%\blind_predictions_locked.csv
echo   7. %OUT%\blind_prediction_determinism.json
echo   8. %OUT%\blind_benchmark_main.csv
echo   9. %OUT%\blind_benchmark_results.json
echo  10. %OUT%\blind_confusion_matrices.csv
echo  11. %OUT%\blind_reliability_bins.csv and %OUT%\qa\blind_reliability_*.png
echo  12. %OUT%\blind_data_quality_breakdown.csv
echo  13. %OUT%\blind_spatial_by_municipality.csv
echo  14. %OUT%\blind_error_cases.csv and %OUT%\qa\blind_error_cases.geojson
echo  15. %OUT%\qa\blind_precision_recall_f1_by_date.png
echo  16. %OUT%\qa\blind_recall_at_frozen_p95_by_date.png
echo  17. %OUT%\blind_benchmark_qa.md and blind_benchmark_qa.json
echo  18. %OUT%\blind_evaluation_manifest.json
echo  19. Every WARN, ERROR, FAIL, MISMATCH, AMBIGUOUS and BLOCKED line under %OUT%\logs
exit /b 0

:fail
echo.
echo VERIFY_RAPSKARTAN_2025_BLIND_TEST: FAIL
echo Return: %OUT%\logs\stopd_verify.log and every *_traceback.log
exit /b 1
