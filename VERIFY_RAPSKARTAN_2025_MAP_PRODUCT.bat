@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "OUT=%~dp0data\derived\rapskartan_v1\2025"
set "STOP_C=C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC"
set "STOP_D=C:\AkerSyncRepo\work\rapskartan_skane_v1_blind_2025_stopD"
if not "%~1"=="" set "OUT=%~1"
if not "%~2"=="" set "STOP_C=%~2"
if not "%~3"=="" set "STOP_D=%~3"

echo ========================================================================================
echo Rapskartan Skane V1 - INDEPENDENT FULL MAP VERIFIER - STOPPUNKT E
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
powershell -NoProfile -Command "& { py -3 -u src\101_verify_rapskartan_2025_map_product.py --output-dir '%OUT%' --stop-c-dir '%STOP_C%' --stop-d-dir '%STOP_D%' 2^>^&1 ^| Tee-Object -FilePath '%OUT%\logs\stope_verify.log'; exit $LASTEXITCODE }"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :fail
for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: verifier changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo VERIFY_RAPSKARTAN_2025_MAP_PRODUCT: PASS
echo STOPPUNKT E - do not start web, deployment, tag, merge or Sentinel-1 without explicit GO WEB PRODUCT.
echo.
echo Return:
echo   1. %OUT%\logs\map_product_tests.log
echo   2. %OUT%\logs\map_product.log
echo   3. %OUT%\logs\stope_verify.log
echo   4. %OUT%\full_map_manifest.json
echo   5. %OUT%\qa\full_map_qa.json
echo   6. %OUT%\qa\local_engine_parity.json
echo   7. %OUT%\qa\local_engine_parity_rows.csv
echo   8. %OUT%\qa\status_distribution.csv
echo   9. %OUT%\qa\municipality_coverage.csv
echo  10. %OUT%\qa\field_scope_inventory.csv
echo  11. %OUT%\source\scene_inventory.json
echo  12. %OUT%\source\scene_archive_inventory.csv
echo  13. %OUT%\source\prior_source_inventory.csv
echo  14. %OUT%\2025-03-15.parquet through %OUT%\2025-06-10.parquet
echo  15. Every WARN, ERROR, FAIL, MISMATCH, AMBIGUOUS and BLOCKED line under %OUT%\logs
exit /b 0

:fail
echo.
echo VERIFY_RAPSKARTAN_2025_MAP_PRODUCT: FAIL
echo NOT READY FOR WEB PRODUCT, FREEZE, TAG OR DEPLOYMENT.
echo Return: %OUT%\logs\stope_verify.log and every *_traceback.log
exit /b 1
