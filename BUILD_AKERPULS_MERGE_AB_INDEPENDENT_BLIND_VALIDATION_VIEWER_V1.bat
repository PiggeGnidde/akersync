@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"
set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_blind_validation_viewer_v1"
echo ============================================================
echo AKERPULS - INDEPENDENT BLIND A/B MERGE VALIDATION VIEWER V1
echo 50 A + 50 B; FIRST 100 AUDIT PAIRS EXCLUDED
echo NO TIER/SCORES/IDS VISIBLE
echo ============================================================
for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo ERROR: wrong branch& exit /b 1)
for /f "delims=" %%S in ('git status --short') do (echo ERROR: working tree must be clean& git status --short& exit /b 1)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%
if exist "%OUT%" (echo ERROR: output already exists: %OUT%& exit /b 1)
echo.
echo [1/2] Independent-validation viewer contract tests
py -3 -m unittest tests.test_akerpuls_merge_ab_independent_blind_validation_viewer_v1 -v
if errorlevel 1 exit /b 1
echo.
echo [2/2] Build deterministic 50+50 blind validation viewer
py -3 -u src\199_akerpuls_merge_ab_independent_blind_validation_viewer_v1.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1
if not exist "%OUT%\index.html" (echo ERROR: index.html missing& exit /b 1)
if not exist "%OUT%\AB_INDEPENDENT_VALIDATION_VIEWER_MANIFEST_V1.json" (echo ERROR: manifest missing& exit /b 1)
echo.
echo ============================================================
echo PASS: independent blind A/B validation viewer built.
echo DO NOT OPEN AB_VALIDATION_BLIND_KEY_DO_NOT_OPEN.csv.
echo NEXT STOP: paste build output; viewer will be frozen before labeling.
echo ============================================================
exit /b 0
