@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "M0=C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_m1_historical_paths_preflight_v1"
if not "%~1"=="" set "OUT=%~1"

echo ============================================================
echo AKERPULS - MERGE M1 HISTORICAL PATH PREFLIGHT V1
echo READ-ONLY SEARCH OF DOCUMENTED AKERMINNE LOCATIONS
echo ============================================================
echo M0_FREEZE_DIR=%M0%
echo OUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before historical-path preflight.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)
if exist "%OUT%" (
  echo ERROR: output directory already exists: %OUT%
  echo Remove only this preflight output directory if you intentionally want to rerun.
  exit /b 1
)

echo.
echo [1/2] Unit tests
py -3 -m unittest tests.test_akerpuls_m1_historical_paths_preflight_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Search documented AkerMinne/M4 locations read-only
py -3 -u src\175_akerpuls_m1_historical_paths_preflight_v1.py --m0-freeze-dir "%M0%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\M1_HISTORICAL_PATH_DISCOVERY_V1.json" (echo ERROR: discovery JSON not created& exit /b 1)
if not exist "%OUT%\M1_HISTORICAL_PATH_DISCOVERY_V1.txt" (echo ERROR: discovery text not created& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during historical-path preflight.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: documented AkerMinne/M4 locations inventoried read-only.
echo No model prediction, fusion, tuning or geometry mutation occurred.
echo OUTPUT=%OUT%
echo NEXT STOP: inspect exact files found before M1 implementation.
echo ============================================================
exit /b 0
