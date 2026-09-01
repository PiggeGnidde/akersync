@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akernorm-product-v1a"
set "CONTEXT_TAG=akerpass-akerminne-context-v1.0"
set "CONTEXT_COMMIT=1ad5c77656bb93664d94254af298009a6620da4f"
set "VALIDATION_TAG=akerscore-akerminne-validation-v1.0"
set "VALIDATION_COMMIT=9ca92418d6c100793dcaf3ae70705c97e556a9d5"
set "SOURCE_REPO=C:\AkerSyncRepo"
set "INPUT=%SOURCE_REPO%\work\akerscore_validation_csv_upload"
set "OUT=%SOURCE_REPO%\work\akernorm_v1_discovery_stopA"
set "LOCALPATHS=%SOURCE_REPO%\config\local_paths.json"
set "TEMP_NC=C:\AkerSyncRaw\smhi\SMHI_pthbv_tas_2011_2025_monthly.nc"
set "PRECIP_NC=C:\AkerSyncRaw\smhi\SMHI_pthbv_pr_2011_2025_monthly.nc"

if not "%~1"=="" set "INPUT=%~1"
if not "%~2"=="" set "OUT=%~2"
if not "%~3"=="" set "LOCALPATHS=%~3"
if not "%~4"=="" set "TEMP_NC=%~4"
if not "%~5"=="" set "PRECIP_NC=%~5"

echo ========================================================================================
echo AkerNorm V1 - DISCOVERY AND REPRODUCTION ONLY - STOPPUNKT A
echo ========================================================================================
echo Input:        %INPUT%
echo Output:       %OUT%
echo Local paths:  %LOCALPATHS%
echo Temperature:  %TEMP_NC%
echo Precipitation:%PRECIP_NC%
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean before discovery.
  git status --short
  exit /b 1
)

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)

for /f "delims=" %%T in ('git rev-list -n 1 "%CONTEXT_TAG%"') do set "CONTEXT_ACTUAL=%%T"
if /I not "%CONTEXT_ACTUAL%"=="%CONTEXT_COMMIT%" (
  echo FAIL: context tag mismatch: %CONTEXT_ACTUAL%
  exit /b 1
)
for /f "delims=" %%T in ('git rev-list -n 1 "%VALIDATION_TAG%"') do set "VALIDATION_ACTUAL=%%T"
if /I not "%VALIDATION_ACTUAL%"=="%VALIDATION_COMMIT%" (
  echo FAIL: validation tag mismatch: %VALIDATION_ACTUAL%
  exit /b 1
)

where py >nul 2>nul
if errorlevel 1 (
  echo FAIL: Python launcher 'py' is missing.
  exit /b 1
)

if not exist "%OUT%\logs" mkdir "%OUT%\logs"
if errorlevel 1 exit /b 1

echo [1/2] Discovery unit tests...
py -3 -m unittest discover -s tests -p "test_akernorm_v1_discovery.py" -v > "%OUT%\logs\discovery_tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\discovery_tests.log"
if not "%RC%"=="0" goto :fail

echo.
echo [2/2] Repository, source and full analysis reproduction...
py -3 src\78_akernorm_v1_discovery.py --input-dir "%INPUT%" --output-dir "%OUT%" --local-paths "%LOCALPATHS%" --temp-netcdf "%TEMP_NC%" --precip-netcdf "%PRECIP_NC%" > "%OUT%\logs\discovery_full.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\discovery_full.log"
if not "%RC%"=="0" goto :fail

for %%F in (
  "%OUT%\discovery_repository_report.md"
  "%OUT%\akernorm_analysis_inventory.md"
  "%OUT%\official_norm_source_report.md"
  "%OUT%\crop_code_contract.json"
  "%OUT%\reproduction_comparison.csv"
  "%OUT%\discovery_manifest.json"
) do (
  if not exist "%%~F" (
    echo FAIL: required STOPPUNKT A artifact is missing: %%~F
    goto :fail
  )
)

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: discovery changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo ========================================================================================
echo AKERNORM V1 DISCOVERY RUNNER: PASS
echo ========================================================================================
echo No model freeze, product code, pilot, full Skane run, web build or Sentinel-2 work ran.
echo.
echo Run the independent verifier next:
echo   VERIFY_AKERNORM_V1_REPRODUCTION.bat "%OUT%"
echo.
echo STOPPUNKT A - return:
echo   1. Full PASS/FAIL summary and %OUT%\logs\discovery_full.log
echo   2. %OUT%\discovery_repository_report.md
echo   3. %OUT%\akernorm_analysis_inventory.md
echo   4. %OUT%\official_norm_source_report.md
echo   5. %OUT%\crop_code_contract.json
echo   6. %OUT%\reproduction_comparison.csv
echo   7. %OUT%\discovery_qa.md
echo   8. %OUT%\discovery_manifest.json
echo   9. Every WARN, ERROR, MISMATCH, AMBIGUOUS and BLOCKED line under %OUT%\logs
exit /b 0

:fail
echo.
echo ========================================================================================
echo AKERNORM V1 DISCOVERY RUNNER: FAIL
echo ========================================================================================
echo Return the complete logs under:
echo   %OUT%\logs
exit /b 1
