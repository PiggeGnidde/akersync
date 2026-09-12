@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_full_skane_d0b_sparse_norm_v1"
set "LOCAL_PATHS=%CD%\config\local_paths.json"
if not "%~1"=="" set "OUT=%~1"
if not "%~2"=="" set "LOCAL_PATHS=%~2"

echo ========================================================================================
echo AkerPuls split fusion QA v1 - FULL SKANE D0B SPARSE NORMALIZATION - ZERO PU
echo ========================================================================================
echo Output:      %OUT%
echo Local paths: %LOCAL_PATHS%
echo.

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: working tree is not clean.
  git status --short
  exit /b 1
)
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.
  exit /b 1
)
where py >nul 2>nul || (echo FAIL: Python launcher py is missing.& exit /b 1)
if not exist "%LOCAL_PATHS%" (echo FAIL: missing %LOCAL_PATHS%& exit /b 1)
if not exist "C:\AkerSyncRepo\work\akerpuls_full_skane_d0_plan_v1\D1_EXECUTION_CONTRACT.json" (
  echo FAIL: D0 execution contract missing.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_full_skane_d0_plan_v1\d0_analysis_cells.csv" (
  echo FAIL: D0 analysis cells missing.
  exit /b 1
)
py -3 -c "import pandas,geopandas,shapely" >nul 2>nul || (
  echo FAIL: required Python dependencies pandas/geopandas/shapely are missing.
  exit /b 1
)

if not exist "%OUT%\logs" mkdir "%OUT%\logs"

py -3 -m unittest tests.test_akerpuls_full_skane_d0b_sparse_norm_v1 -v > "%OUT%\logs\tests.log" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%\logs\tests.log"
if not "%RC%"=="0" goto :fail

echo.
echo D0b resolver starts now. No STAC, no Process API, zero PU.
echo.
py -3 -u src\139_akerpuls_full_skane_d0b_sparse_norm_v1.py --local-paths "%LOCAL_PATHS%" --output-dir "%OUT%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :review

for %%F in (
  "%OUT%\d0b_resolved_normalization_windows.csv"
  "%OUT%\d0b_resolved_normalization_windows.gpkg"
  "%OUT%\d0b_sparse_cell_resolution.csv"
  "%OUT%\D1_EXECUTION_CONTRACT_FINAL.json"
  "%OUT%\d0b_manifest.json"
) do if not exist "%%~F" (echo FAIL: missing artifact %%~F& goto :fail)

for /f "delims=" %%S in ('git status --short') do (
  echo FAIL: D0b changed Git-visible files.
  git status --short
  goto :fail
)

echo.
echo ========================================================================================
echo STOPPUNKT D0B: PASS - SPARSE NORMALIZATION RESOLVED, ZERO PU
echo ========================================================================================
echo Return the console summary to ChatGPT before D1 is implemented/run.
echo.
exit /b 0

:review
echo.
echo ========================================================================================
echo STOPPUNKT D0B: REVIEW REQUIRED - DO NOT START D1
 echo ========================================================================================
echo D0b used zero PU. Return the console output to ChatGPT.
exit /b %RC%

:fail
echo.
echo ========================================================================================
echo STOPPUNKT D0B: FAIL - DO NOT START D1
 echo ========================================================================================
exit /b 1
