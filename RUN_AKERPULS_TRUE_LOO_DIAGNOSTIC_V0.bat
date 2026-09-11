@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_true_loo_diagnostic_v0"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)

where py >nul 2>nul || (
  echo FAIL: Python launcher py is missing.
  exit /b 1
)

py -3 -c "import numpy,pandas,scipy,geopandas,rasterio" >nul 2>nul || (
  echo FAIL: required Python dependencies are missing in py -3 environment.
  exit /b 1
)

if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c2_validation\c2_field_validation.csv" (
  echo FAIL: C2 validation output missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c5c_validation\c5c_field_validation.csv" (
  echo FAIL: C5C validation output missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c3_qa\c3_BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv" (
  echo FAIL: C3 blind key missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c5d_blind_qa\c5d_BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv" (
  echo FAIL: C5D blind key missing.
  exit /b 1
)

echo ========================================================================================
echo AkerPuls 2026 - C6 TRUE LEAVE-ONE-DATE-OUT SEGMENTATION DIAGNOSTIC - ZERO PU
echo ========================================================================================

py -3 -m unittest tests.test_akerpuls_true_loo_diagnostic tests.test_akerpuls_true_loo_runner -v
if errorlevel 1 exit /b 1

py -3 src\133_akerpuls_true_loo_diagnostic_runner.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

endlocal
