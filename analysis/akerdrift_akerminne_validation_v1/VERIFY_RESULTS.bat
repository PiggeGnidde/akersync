@echo off
setlocal
chcp 65001 >nul
cd /d C:\AkerSyncRepo

set "DRIFT_INPUT=C:\AkerSyncRepo\work\akerdrift_akerminne_validation_inputs\akerdrift_akerminne_validation_inputs.zip"
set "HISTORY_INPUT=C:\AkerSyncRepo\work\akerscore_validation_csv_upload.zip"
set "OUT_DIR=C:\AkerSyncRepo\work\akerdrift_akerminne_validation_v1"

echo ========================================================================================
echo AkerDrift x AkerMinne validation v1.0 verifier
echo ========================================================================================
echo.

if not exist "%DRIFT_INPUT%" (
  echo FAIL: missing %DRIFT_INPUT%
  exit /b 1
)
if not exist "%HISTORY_INPUT%" (
  echo FAIL: missing %HISTORY_INPUT%
  exit /b 1
)

python analysis\akerdrift_akerminne_validation_v1\run_analysis.py ^
  --drift-input "%DRIFT_INPUT%" ^
  --history-input "%HISTORY_INPUT%" ^
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
