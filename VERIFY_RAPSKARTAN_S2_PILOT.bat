@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "OUT=C:\AkerSyncRepo\work\rapskartan_skane_v1_s2_pilot_stopB"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo Rapskartan Skane V1 - INDEPENDENT SENTINEL-2 DATAPILOT VERIFIER - STOPPUNKT B
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
py -3 src\93_verify_rapskartan_s2_pilot.py --output-dir "%OUT%" > "%OUT%\logs\stopb_verify.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\stopb_verify.log"
if not "%RC%"=="0" goto :fail
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: verifier changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo VERIFY_RAPSKARTAN_S2_PILOT: PASS
echo STOPPUNKT B - do not start model development without explicit GO MODELLUTVECKLING.
echo.
echo Return:
echo   1. %OUT%\logs\s2_pilot_tests.log
echo   2. %OUT%\logs\s2_pilot.log
echo   3. %OUT%\logs\stopb_verify.log
echo   4. %OUT%\s2_pilot_contract.json
echo   5. %OUT%\pilot_selection.csv
echo   6. %OUT%\field_timeseries.csv
echo   7. %OUT%\scl_timeseries.csv
echo   8. %OUT%\edge_rule_summary.csv
echo   9. %OUT%\cloud_mask_examples.csv
echo  10. %OUT%\api_request_inventory.csv
echo  11. %OUT%\determinism_rerun.json
echo  12. %OUT%\runtime_volume.json and cache_inventory.json
echo  13. %OUT%\pilot_qa.md and pilot_qa.json
echo  14. %OUT%\s2_pilot_manifest.json
echo  15. %OUT%\qa\*.png and %OUT%\source\stac_*.json
echo  16. Every WARN, ERROR, FAIL, MISMATCH, AMBIGUOUS and BLOCKED line under %OUT%\logs
exit /b 0

:fail
echo.
echo VERIFY_RAPSKARTAN_S2_PILOT: FAIL
echo No model development or later phase ran.
echo Return: %OUT%\logs\stopb_verify.log
exit /b 1
