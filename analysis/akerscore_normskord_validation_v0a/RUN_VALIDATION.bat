@echo off
setlocal
chcp 65001 >nul

echo ====================================================================================
echo AkerScore x Normskord validation v0a
 echo ====================================================================================
echo.

set "INPUT=C:\AkerSyncRepo\work\akerscore_validation_csv_upload"
if not "%~1"=="" set "INPUT=%~1"
set "OUT=C:\AkerSyncRepo\work\akerscore_normskord_validation_v0a"
set "SCRIPT=%~dp0run_validation.py"

if not exist "%INPUT%\field_static_context_selected.csv.gz" (
  echo FAIL: frozen validation input folder is missing.
  echo Expected:
  echo   %INPUT%
  exit /b 1
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%SCRIPT%" --input-dir "%INPUT%" --output-dir "%OUT%"
  if not errorlevel 1 goto :pass
)

python "%SCRIPT%" --input-dir "%INPUT%" --output-dir "%OUT%"
if errorlevel 1 goto :fail

:pass
echo.
echo ====================================================================================
echo RUN_VALIDATION: PASS
echo ====================================================================================
echo Results:
echo   %OUT%\results.json
echo   %OUT%\sko_fit_table.csv
echo   %OUT%\akerscore_to_normyield_curve.csv
exit /b 0

:fail
echo.
echo ====================================================================================
echo RUN_VALIDATION: FAIL
echo ====================================================================================
exit /b 1
