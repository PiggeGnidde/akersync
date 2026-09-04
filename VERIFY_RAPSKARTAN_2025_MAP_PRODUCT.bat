@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
set "VERIFY_OUT=%~dp0data\derived\rapskartan_v1\2025_map_product_v3"
set "VERIFY_STOP_C=C:\AkerSyncRepo\work\rapskartan_skane_v1_model_stopC"
set "VERIFY_STOP_D=C:\AkerSyncRepo\work\rapskartan_skane_v1_blind_2025_stopD"
if not "%~1"=="" set "VERIFY_OUT=%~1"
if not "%~2"=="" set "VERIFY_STOP_C=%~2"
if not "%~3"=="" set "VERIFY_STOP_D=%~3"
echo Independent STOPPUNKT E verifier - accepted V3, offline only.
py -3 -u src\101_verify_rapskartan_2025_map_product.py --output-dir "%VERIFY_OUT%" --stop-c-dir "%VERIFY_STOP_C%" --stop-d-dir "%VERIFY_STOP_D%"
if errorlevel 1 (
  echo STOPPUNKT E: FAIL. Return the error and stope_verify.log. No web is authorized.
  exit /b 1
)
echo STOPPUNKT E: PASS. Return the ZIP named above for review.
exit /b 0
