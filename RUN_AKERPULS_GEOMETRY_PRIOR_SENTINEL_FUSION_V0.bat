@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "ROLLING=C:\AkerSyncRepo\work\akerpuls_geometry_rolling_backtest_v0"
set "C3=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c3_qa\c3_BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv"
set "C5D=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_c5d_blind_qa\c5d_BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv"
set "OUT=C:\AkerSyncRepo\work\akerpuls_geometry_prior_sentinel_fusion_v0"

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)

where py >nul 2>nul || (
  echo FAIL: Python launcher py is missing.
  exit /b 1
)

py -3 -c "import numpy,pandas,scipy" >nul 2>nul || (
  echo FAIL: required Python packages numpy/pandas/scipy are missing in py -3.
  exit /b 1
)

if not exist "%ROLLING%\field_prior_2026_preview.csv" (
  echo FAIL: rolling 2026 prior preview not found:
  echo   %ROLLING%\field_prior_2026_preview.csv
  exit /b 1
)
if not exist "%C3%" (
  echo FAIL: C3 blind key not found:
  echo   %C3%
  exit /b 1
)
if not exist "%C5D%" (
  echo FAIL: C5D blind key not found:
  echo   %C5D%
  exit /b 1
)

echo ========================================================================================
echo AkerPuls 2026 - GEOMETRY PRIOR + SENTINEL FUSION DIAGNOSTIC - ZERO PU
 echo ========================================================================================
echo No threshold tuning. No new split rule. Frozen visual labels are reused as-is.
echo.

py -3 -m unittest tests.test_akerpuls_geometry_prior_sentinel_fusion -v
if errorlevel 1 exit /b 1

py -3 src\131_akerpuls_geometry_prior_sentinel_fusion.py --rolling-dir "%ROLLING%" --c3-key "%C3%" --c5d-key "%C5D%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

endlocal
