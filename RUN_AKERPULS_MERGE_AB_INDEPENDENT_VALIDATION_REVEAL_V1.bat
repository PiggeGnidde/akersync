@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_validation_reveal_v1"

echo ============================================================
echo AKERPULS - INDEPENDENT A/B MERGE VALIDATION ANALYSIS
echo PRIMARY: BROAD A VS B
echo SECONDARY: STRICT A VS B
echo ============================================================

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo ERROR: wrong branch& exit /b 1)
for /f "delims=" %%S in ('git status --short') do (echo ERROR: working tree must be clean& git status --short& exit /b 1)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if exist "%OUT%" (echo ERROR: output already exists: %OUT%& exit /b 1)

echo.
echo [1/2] Analysis contract tests
py -3 -m unittest tests.test_akerpuls_merge_ab_independent_validation_reveal_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Run independent validation analysis
py -3 -u src\202_akerpuls_merge_ab_independent_validation_reveal_v1.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\MERGE_AB_INDEPENDENT_VALIDATION_SUMMARY_V1.json" (echo ERROR: summary missing& exit /b 1)
if not exist "%OUT%\MERGE_AB_INDEPENDENT_VALIDATION_CONTRASTS.csv" (echo ERROR: contrast output missing& exit /b 1)

echo.
echo ============================================================
echo PASS: independent A/B validation analyzed.
echo No fusion/tuning/automatic merge/geometry mutation performed.
echo NEXT STOP: inspect A vs B result before operational merge policy.
echo ============================================================
exit /b 0
