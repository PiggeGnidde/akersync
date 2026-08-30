@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0\..\.."

echo ====================================================================================
echo AkerScore x AkerMinne validation v1.0 - reproduce and verify
echo ====================================================================================
echo.

set "INPUT=C:\AkerSyncRepo\work\akerscore_validation_csv_upload"
set "OUT=C:\AkerSyncRepo\work\akerscore_akerminne_validation_v1"
set "SCRIPT=C:\AkerSyncRepo\analysis\akerscore_akerminne_validation_v1\run_validation.py"

if not exist "%INPUT%\field_static_context_selected.csv.gz" (
  echo FAIL: validation input folder is missing.
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
echo VERIFY_RESULTS: PASS
echo ====================================================================================
echo Results:
echo   %OUT%\results.json
echo   %OUT%\verification.json
exit /b 0

:fail
echo.
echo ====================================================================================
echo VERIFY_RESULTS: FAIL
echo ====================================================================================
exit /b 1
