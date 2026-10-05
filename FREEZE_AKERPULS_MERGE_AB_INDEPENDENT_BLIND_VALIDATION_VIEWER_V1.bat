@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_blind_validation_viewer_freeze_v1"

echo ============================================================
echo AKERPULS - FREEZE INDEPENDENT BLIND A/B VALIDATION VIEWER
echo PRE-LABEL FREEZE: SAMPLE + RENDERING + ANALYSIS CONTRACT
echo ============================================================

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo ERROR: wrong branch& exit /b 1)
for /f "delims=" %%S in ('git status --short') do (echo ERROR: working tree must be clean& git status --short& exit /b 1)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if exist "%OUT%" (echo ERROR: freeze output already exists: %OUT%& exit /b 1)

echo.
echo [1/2] Viewer-freeze contract tests
py -3 -m unittest tests.test_akerpuls_merge_ab_independent_blind_validation_viewer_freeze_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Verify exact sample/rendering and formally freeze before labeling
py -3 -u src\200_akerpuls_merge_ab_independent_blind_validation_viewer_freeze_v1.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_VIEWER_FREEZE_V1.json" (echo ERROR: freeze JSON missing& exit /b 1)
if not exist "%OUT%\AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_VIEWER_FREEZE_V1.sha256" (echo ERROR: freeze SHA missing& exit /b 1)

echo.
echo ============================================================
echo PASS: independent blind A/B viewer formally frozen pre-label.
echo DO NOT OPEN AB_VALIDATION_BLIND_KEY_DO_NOT_OPEN.csv.
echo NEXT: open viewer index.html and label all 100 pairs.
echo ============================================================
exit /b 0
