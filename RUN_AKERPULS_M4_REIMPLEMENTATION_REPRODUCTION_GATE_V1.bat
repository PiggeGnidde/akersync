@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_m4_reproduction_gate_v1"
if not "%~1"=="" set "OUT=%~1"

echo ============================================================
echo AKERPULS - M4 REIMPLEMENTATION REPRODUCTION GATE V1
echo YEAR-BLIND 2021-2025 ONLY; 2026 REMAINS UNOPENED
echo ============================================================
echo OUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before M4 reproduction gate.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)

for /f "delims=" %%V in ('py -3 -c "import importlib.metadata as m; print(m.version('lightgbm') if True else '')" 2^>nul') do set "LGBVER=%%V"
if not "%LGBVER%"=="4.7.0" (
  echo.
  echo ERROR: exact dependency lightgbm==4.7.0 is required.
  echo Current lightgbm=%LGBVER%
  echo Install it explicitly with:
  echo   py -3 -m pip install lightgbm==4.7.0
  echo Then rerun this BAT.
  exit /b 1
)

echo LIGHTGBM=%LGBVER%
if exist "%OUT%" (
  echo ERROR: output directory already exists: %OUT%
  echo Do not overwrite reproduction evidence. Use a new output directory for a deliberate rerun.
  exit /b 1
)

echo.
echo [1/2] Contract/unit tests
py -3 -m unittest tests.test_akerpuls_m4_reimplementation_reproduction_gate_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Run persistent year-blind M4 reproduction gate
py -3 -u src\179_akerpuls_m4_reimplementation_reproduction_gate_v1.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\REPRODUCTION_SUMMARY.json" (echo ERROR: reproduction summary missing& exit /b 1)
if not exist "%OUT%\FEATURE_CONTRACT.json" (echo ERROR: feature contract missing& exit /b 1)
if not exist "%OUT%\ENVIRONMENT.json" (echo ERROR: environment record missing& exit /b 1)
if not exist "%OUT%\SHA256_MANIFEST.txt" (echo ERROR: SHA manifest missing& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during reproduction gate.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo COMPLETE: persistent M4 reproduction gate finished.
echo Inspect STATUS above. 2026 was not predicted.
echo OUTPUT=%OUT%
echo ============================================================
exit /b 0
