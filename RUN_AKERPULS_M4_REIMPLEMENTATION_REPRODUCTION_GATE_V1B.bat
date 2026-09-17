@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_m4_reproduction_gate_v1b"
if not "%~1"=="" set "OUT=%~1"

echo ============================================================
echo AKERPULS - M4 REIMPLEMENTATION REPRODUCTION GATE V1B
echo EXACT NO_PUBLIC_MATCH VALIDITY RULE, YEAR-BLIND 2021-2025
echo 2026 REMAINS UNOPENED
echo ============================================================
echo OUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before M4 reproduction V1B.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

where py >nul 2>nul || (echo ERROR: Python launcher py not found.& exit /b 1)
for /f "delims=" %%V in ('py -3 -c "import importlib.metadata as m; print(m.version('lightgbm'))" 2^>nul') do set "LGBVER=%%V"
if not "%LGBVER%"=="4.7.0" (
  echo ERROR: exact dependency lightgbm==4.7.0 is required. Current=%LGBVER%
  exit /b 1
)
if exist "%OUT%" (
  echo ERROR: output directory already exists: %OUT%
  echo Preserve prior evidence. Use a new output directory for a deliberate rerun.
  exit /b 1
)
if not exist "C:\AkerSyncRepo\work\akerpuls_m4_target_census_diagnostic_v1\M4_TARGET_CENSUS_DIAGNOSTIC_V1.json" (
  echo ERROR: exact target-census diagnostic evidence is missing.
  exit /b 1
)

echo.
echo [1/2] V1B contract/unit tests
py -3 -m unittest tests.test_akerpuls_m4_reimplementation_reproduction_gate_v1b -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Run persistent M4 reproduction V1B
py -3 -u src\181_akerpuls_m4_reimplementation_reproduction_gate_v1b.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\REPRODUCTION_SUMMARY.json" (echo ERROR: reproduction summary missing& exit /b 1)
if not exist "%OUT%\FEATURE_CONTRACT.json" (echo ERROR: feature contract missing& exit /b 1)
if not exist "%OUT%\V1B_TARGET_VALIDITY_PROVENANCE.json" (echo ERROR: V1B provenance missing& exit /b 1)
if not exist "%OUT%\SHA256_MANIFEST.txt" (echo ERROR: SHA manifest missing& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during M4 reproduction V1B.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo COMPLETE: M4 reproduction V1B finished and persisted.
echo Inspect STATUS above. 2026 was not predicted.
echo V1 failed evidence remains untouched at:
echo C:\AkerSyncRepo\work\akerpuls_m4_reproduction_gate_v1
echo OUTPUT=%OUT%
echo ============================================================
exit /b 0
