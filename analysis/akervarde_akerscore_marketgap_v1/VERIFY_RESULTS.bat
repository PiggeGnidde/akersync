@echo off
setlocal
chcp 65001 >nul
cd /d C:\AkerSyncRepo

set "AV_INPUT=C:\AkerSyncRegression\work\akervarde_residual_inputs.zip"
set "SCORE_INPUT=C:\AkerSyncRepo\work\akerscore_validation_csv_upload.zip"
set "OUT_DIR=C:\AkerSyncRepo\work\akervarde_akerscore_marketgap_v1"

echo ========================================================================================
echo AkerVarde x AkerScore market-gap v1.0 verifier
echo ========================================================================================
echo.

if not exist "%AV_INPUT%" (
  echo FAIL: missing %AV_INPUT%
  exit /b 1
)

if not exist "%SCORE_INPUT%" (
  echo FAIL: missing %SCORE_INPUT%
  exit /b 1
)

python analysis\akervarde_akerscore_marketgap_v1\run_analysis.py ^
  --akervarde-input "%AV_INPUT%" ^
  --akerscore-input "%SCORE_INPUT%" ^
  --out-dir "%OUT_DIR%"

if errorlevel 1 (
  echo.
  echo VERIFY_RESULTS: FAIL
  exit /b 1
)

echo.
echo VERIFY_RESULTS: PASS
echo Output: %OUT_DIR%
exit /b 0
