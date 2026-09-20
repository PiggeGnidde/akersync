@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_sh_gated_ranking_v1"

echo ============================================================
echo AKERPULS - S2026/HPRIOR GATED MERGE RANKING V1
echo S2026 = legacy frozen M0 satellite signal
echo Hprior = legacy frozen M1 history prior
echo SAME-BLOCK ONLY; BLOCK BOUNDARY = HARD WALL
echo NO CONTINUOUS FUSION / NO AUTO MERGE
echo ============================================================
echo OUTPUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if exist "%OUT%" (
  echo ERROR: ranking output already exists: %OUT%
  echo Preserve prior evidence; do not overwrite.
  exit /b 1
)

echo.
echo [1/2] S2026/Hprior gated-ranking contract tests
py -3 -m unittest tests.test_akerpuls_merge_sh_gated_ranking_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Build full frozen-pair gated ranking
py -3 -u src\197_akerpuls_merge_sh_gated_ranking_v1.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\MERGE_SH_GATED_RANKING_SUMMARY_V1.json" (echo ERROR: summary missing& exit /b 1)
if not exist "%OUT%\MERGE_SH_GATED_RANKING_V1.parquet" (echo ERROR: ranking parquet missing& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during ranking build.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: S2026/Hprior gated merge ranking built.
echo Still review-only. No boundary has been removed.
echo NEXT STOP: inspect tier census before validation sampling.
echo ============================================================
exit /b 0
