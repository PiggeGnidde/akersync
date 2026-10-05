@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"
set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_final_skane_review_map_v1"

echo ============================================================
echo AKERPULS - FINAL SKANE 2026 SPLIT + MERGE PROPOSAL REVIEW MAP
echo ============================================================
for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo ERROR: wrong branch& exit /b 1)
for /f "delims=" %%S in ('git status --short') do (echo ERROR: working tree must be clean& git status --short& exit /b 1)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%
if exist "%OUT%" (echo ERROR: output already exists: %OUT%& exit /b 1)

echo.
echo [1/2] Final-map contract tests
py -3 -m unittest tests.test_akerpuls_final_skane_review_map_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Build final browser review map from frozen proposal package
py -3 -u src\212_akerpuls_final_skane_review_map_v1.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\index.html" (echo ERROR: map index missing& exit /b 1)
if not exist "%OUT%\AKERPULS_FINAL_SKANE_REVIEW_MAP_V1_MANIFEST.json" (echo ERROR: map manifest missing& exit /b 1)

echo.
echo ============================================================
echo PASS: final Skane proposal review map built.
echo NEXT: OPEN_AKERPULS_FINAL_SKANE_REVIEW_MAP_V1.bat
echo ============================================================
exit /b 0
