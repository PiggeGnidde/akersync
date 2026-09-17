@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "M0=C:\AkerSyncRepo\work\akerpuls_merge_m0_satellite_only_freeze_v1"
set "INPUTS=C:\AkerSyncRepo\work\akerscore_validation_csv_upload"
set "OUT=C:\AkerSyncRepo\work\akerpuls_m4_reimplementation_input_profile_v1"
if not "%~1"=="" set "OUT=%~1"

echo ============================================================
echo AKERPULS - M4 REIMPLEMENTATION INPUT PROFILE V1
echo VERIFY FROZEN INPUTS + PROFILE LABELS + ML ENVIRONMENT
echo ============================================================
echo M0_FREEZE_DIR=%M0%
echo INPUT_DIR=%INPUTS%
echo OUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before M4 input profile.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)
if exist "%OUT%" (
  echo ERROR: output directory already exists: %OUT%
  echo Remove only this profile output directory if you intentionally want to rerun.
  exit /b 1
)

echo.
echo [1/2] Unit tests
py -3 -m unittest tests.test_akerpuls_m4_reimplementation_input_profile_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Verify and profile exact frozen M4 inputs
py -3 -u src\178_akerpuls_m4_reimplementation_input_profile_v1.py --m0-freeze-dir "%M0%" --input-dir "%INPUTS%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\M4_REIMPLEMENTATION_INPUT_PROFILE_V1.json" (echo ERROR: profile JSON not created& exit /b 1)
if not exist "%OUT%\M4_REIMPLEMENTATION_INPUT_PROFILE_V1.txt" (echo ERROR: profile text not created& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during M4 input profile.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: frozen M4 inputs verified and profiled.
echo No model fit, 2026 prediction, fusion, tuning or geometry mutation occurred.
echo OUTPUT=%OUT%
echo NEXT STOP: use exact label domains + package versions to build reproduction gate.
echo ============================================================
exit /b 0
