@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_m1_m4_pair_prior_v1"

echo ============================================================
echo AKERPULS MERGE M1 - M4 PAIR PRIOR V1
echo EXACT FROZEN 27146 M0 PAIR UNIVERSE
echo HISTORY/CONTEXT ONLY; NO M0 SATELLITE EVIDENCE / NO FUSION
echo ============================================================
echo OUTPUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before M1 pair-prior generation.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if exist "%OUT%" (
  echo ERROR: output directory already exists: %OUT%
  echo Preserve prior M1 evidence; do not overwrite.
  exit /b 1
)
py -3 -c "import pyarrow" >nul 2>nul
if errorlevel 1 (
  echo ERROR: pyarrow is required.
  exit /b 1
)

echo.
echo [1/2] M1 independence/contract tests
py -3 -m unittest tests.test_akerpuls_merge_m1_m4_pair_prior_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Generate independent M4 pair-prior features
py -3 -u src\185_akerpuls_merge_m1_m4_pair_prior_v1.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\M1_M4_PAIR_PRIOR.parquet" (echo ERROR: M1 Parquet missing& exit /b 1)
if not exist "%OUT%\M1_M4_PAIR_PRIOR_SUMMARY_V1.json" (echo ERROR: M1 summary missing& exit /b 1)
if not exist "%OUT%\SHA256_MANIFEST.txt" (echo ERROR: M1 SHA manifest missing& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during M1 generation.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: independent M1 M4 pair-prior generated for freeze review.
echo No M0 satellite scores/status, fusion, thresholds or geometry mutation used.
echo OUTPUT=%OUT%
echo NEXT STOP: inspect M1 distributions/hashes, then formal freeze.
echo ============================================================
exit /b 0
