@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "OUT=C:\AkerSyncRepo\work\rapskartan_skane_v1_discovery_stopA"
if not "%~1"=="" set "OUT=%~1"

echo ========================================================================================
echo Rapskartan Skane V1 - INDEPENDENT DISCOVERY VERIFIER - STOPPUNKT A
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
py -3 src\91_verify_rapskartan_v1_discovery.py --output-dir "%OUT%" > "%OUT%\logs\stopa_verify.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\stopa_verify.log"
if not "%RC%"=="0" goto :fail
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: verifier changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo VERIFY_RAPSKARTAN_V1_DISCOVERY: PASS
echo STOPPUNKT A - do not continue without explicit GO SENTINEL-2 DATAPILOT.
echo.
echo Return:
echo   1. %OUT%\logs\discovery_tests.log
echo   2. %OUT%\logs\discovery_full.log
echo   3. %OUT%\logs\stopa_verify.log
echo   4. %OUT%\discovery_repository_report.md
echo   5. %OUT%\crop_ground_truth_inventory.csv
echo   6. %OUT%\crop_code_contract.json
echo   7. %OUT%\ground_truth_source.json
echo   8. %OUT%\geometry_lineage.md and geometry_lineage.json
echo   9. %OUT%\satellite_access_report.md and satellite_access.json
echo  10. %OUT%\temporal_cutoff_contract.json
echo  11. %OUT%\cache_storage_estimate.json
echo  12. %OUT%\discovery_qa.md
echo  13. %OUT%\discovery_manifest.json
echo  14. Every WARN, ERROR, AMBIGUOUS, MISMATCH and BLOCKED line under %OUT%\logs
exit /b 0

:fail
echo.
echo VERIFY_RAPSKARTAN_V1_DISCOVERY: FAIL
echo Return: %OUT%\logs\stopa_verify.log
exit /b 1

