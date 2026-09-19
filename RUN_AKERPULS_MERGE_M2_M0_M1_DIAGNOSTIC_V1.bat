@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_m2_m0_m1_diagnostic_v1"

echo ============================================================
echo AKERPULS MERGE M2 - FROZEN M0 vs FROZEN M1 DIAGNOSTIC
echo ASSOCIATION + DISAGREEMENT ONLY
echo NO FUSION / NO SIGN / NO HUMAN LABEL / NO RETUNING
echo ============================================================
echo OUTPUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before M2 diagnostic.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if exist "%OUT%" (
  echo ERROR: output directory already exists: %OUT%
  echo Preserve prior evidence; do not overwrite.
  exit /b 1
)
py -3 -c "import pyarrow" >nul 2>nul
if errorlevel 1 (echo ERROR: pyarrow is required.& exit /b 1)

echo.
echo [1/2] M2 diagnostic contract tests
py -3 -m unittest tests.test_akerpuls_merge_m2_m0_m1_diagnostic_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Compare frozen M0 and frozen M1 descriptively
py -3 -u src\188_akerpuls_merge_m2_m0_m1_diagnostic_v1.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\M2_M0_M1_DIAGNOSTIC_SUMMARY_V1.json" (echo ERROR: M2 summary missing& exit /b 1)
if not exist "%OUT%\M2_M0_M1_DIAGNOSTIC_JOIN.parquet" (echo ERROR: M2 join missing& exit /b 1)
if not exist "%OUT%\SHA256_MANIFEST.txt" (echo ERROR: M2 manifest missing& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during M2 diagnostic.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: M2 M0-vs-M1 diagnostic completed.
echo No fusion score, sign selection, human labels, tuning or geometry mutation occurred.
echo OUTPUT=%OUT%
echo NEXT STOP: inspect association/disagreement before human-audit design.
echo ============================================================
exit /b 0
