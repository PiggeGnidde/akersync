@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "FREEZE=C:\AkerSyncRepo\work\akerpuls_m4_reimplementation_v1b_freeze\AKERPULS_M4_REIMPLEMENTATION_V1B_FREEZE.json"
set "OUT=C:\AkerSyncRepo\work\akerpuls_m4_2026_prior_v1"

echo ============================================================
echo AKERPULS - FINAL M4 2026 PRIOR V1
echo TRAIN 2018-2025; PREDICT BLIND 2026; PERSIST EVERYTHING
echo NO SATELLITE / M0 MERGE / 2026 CROP LABELS
echo ============================================================
echo OUTPUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before final M4 2026 prior.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if not exist "%FREEZE%" (
  echo ERROR: formal M4 V1B freeze is missing.
  exit /b 1
)
if exist "%OUT%" (
  echo ERROR: output directory already exists: %OUT%
  echo Preserve prior evidence; do not overwrite.
  exit /b 1
)

for /f "delims=" %%V in ('py -3 -c "import importlib.metadata as m; print(m.version('lightgbm'))" 2^>nul') do set "LGBVER=%%V"
if not "%LGBVER%"=="4.7.0" (
  echo ERROR: lightgbm==4.7.0 required. Current=%LGBVER%
  exit /b 1
)

py -3 -c "import pyarrow; print(pyarrow.__version__)" >nul 2>nul
if errorlevel 1 (
  echo ERROR: pyarrow is required for the canonical Parquet prior.
  echo Install with:
  echo   py -3 -m pip install pyarrow
  echo Then rerun this BAT.
  exit /b 1
)

echo.
echo [1/2] Final-2026 contract/unit tests
py -3 -m unittest tests.test_akerpuls_m4_final_2026_prior_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Train final M4 and persist blind 2026 prior
py -3 -u src\183_akerpuls_m4_final_2026_prior_v1.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\model\M4_2026_FINAL.txt" (echo ERROR: final model missing& exit /b 1)
if not exist "%OUT%\M4_2026_FIELD_PRIOR.parquet" (echo ERROR: Parquet prior missing& exit /b 1)
if not exist "%OUT%\M4_2026_DIAGNOSTICS.json" (echo ERROR: diagnostics missing& exit /b 1)
if not exist "%OUT%\SHA256_MANIFEST.txt" (echo ERROR: SHA manifest missing& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during final M4 2026 prior run.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: final M4 2026 prior trained and persisted for freeze review.
echo No Sentinel, merge M0 evidence or 2026 crop labels were used.
echo OUTPUT=%OUT%
echo NEXT STOP: inspect diagnostics/hashes before formal 2026-prior freeze.
echo ============================================================
exit /b 0
