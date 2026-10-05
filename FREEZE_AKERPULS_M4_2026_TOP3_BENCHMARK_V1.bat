@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_m4_2026_top3_benchmark_freeze_v1"

echo ============================================================
echo AKERPULS - FREEZE BLIND M4 2026 TOP-3 BENCHMARK
echo Seal all 128636 predictions before future ground truth
echo ============================================================

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo ERROR: wrong branch& exit /b 1)
for /f "delims=" %%S in ('git status --short') do (echo ERROR: working tree must be clean& git status --short& exit /b 1)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if exist "%OUT%" (echo ERROR: freeze output already exists: %OUT%& exit /b 1)

echo.
echo [1/2] Freeze contract tests
py -3 -m unittest tests.test_akerpuls_m4_2026_top3_benchmark_freeze_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Verify and seal prospective Top-3 prediction set
py -3 -u src\214_akerpuls_m4_2026_top3_benchmark_freeze_v1.py
if errorlevel 1 exit /b 1

if not exist "%OUT%\AKERPULS_M4_2026_TOP3_BENCHMARK_FREEZE_V1.json" (echo ERROR: freeze JSON missing& exit /b 1)

echo.
echo ============================================================
echo PASS: blind M4 2026 Top-3 benchmark formally sealed.
echo No future 2026 truth may be used to retune this prediction set.
echo STOP HERE and paste output.
echo ============================================================
exit /b 0
