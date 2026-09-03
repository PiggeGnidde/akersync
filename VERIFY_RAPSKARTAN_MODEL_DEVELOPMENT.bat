@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "OUT=C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo Rapskartan Skane V1 - INDEPENDENT PRE-BLIND VERIFIER - STOPPUNKT C
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
if not exist "%OUT%\logs" mkdir "%OUT%\logs"
py -3 src\96_verify_rapskartan_model_freeze.py --output-dir "%OUT%" > "%OUT%\logs\stopc_verify.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\stopc_verify.log"
if not "%RC%"=="0" goto :fail
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: verifier changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo VERIFY_RAPSKARTAN_MODEL_DEVELOPMENT: PASS
echo STOPPUNKT C - do not open 2025 labels or create blind predictions without explicit GO 2025 BLIND TEST.
echo.
echo Return:
echo   1. %OUT%\logs\model_tests.log
echo   2. %OUT%\logs\model_dataset.log
echo   3. %OUT%\logs\model_training.log
echo   4. %OUT%\logs\stopc_verify.log
echo   5. %OUT%\development_dataset_manifest.json
echo   6. %OUT%\rapskartan_model_contract_v1.json
echo   7. %OUT%\feature_contract_v1.json
echo   8. %OUT%\threshold_contract_v1.json
echo   9. %OUT%\calibration_contract_v1.json
echo  10. %OUT%\development_cv_results.json
echo  11. %OUT%\development_cv_by_cutoff.csv
echo  12. %OUT%\development_cv_by_year.csv
echo  13. %OUT%\development_geographic_robustness.csv
echo  14. %OUT%\development_reliability_bins.csv and %OUT%\qa\reliability_*.png
echo  15. %OUT%\model_artifacts_manifest.json
echo  16. Every WARN, ERROR, FAIL, MISMATCH, AMBIGUOUS and BLOCKED line under %OUT%\logs
exit /b 0

:fail
echo.
echo VERIFY_RAPSKARTAN_MODEL_DEVELOPMENT: FAIL
echo NOT READY FOR 2025 BLIND TEST.
echo Return: %OUT%\logs\stopc_verify.log and every *_traceback.log
exit /b 1
