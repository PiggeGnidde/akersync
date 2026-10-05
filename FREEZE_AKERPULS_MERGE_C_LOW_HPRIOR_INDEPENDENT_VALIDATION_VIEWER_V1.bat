@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"
set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_c_low_hprior_independent_validation_viewer_freeze_v1"

echo ============================================================
echo AKERPULS - FREEZE TARGETED LOW-HPRIOR C VALIDATION VIEWER
echo PRE-LABEL FREEZE: 29 C + 29 MATCHED CONTROLS
echo ============================================================

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo ERROR: wrong branch& exit /b 1)
for /f "delims=" %%S in ('git status --short') do (echo ERROR: working tree must be clean& git status --short& exit /b 1)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if exist "%OUT%" (echo ERROR: freeze output already exists: %OUT%& exit /b 1)

echo.
echo [1/2] Viewer-freeze contract tests
py -3 -m unittest tests.test_akerpuls_merge_c_low_hprior_independent_validation_viewer_freeze_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Verify exact matched sample/rendering and freeze before labeling
py -3 -u src\205_akerpuls_merge_c_low_hprior_independent_validation_viewer_freeze_v1.py --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\AKERPULS_MERGE_C_LOW_HPRIOR_INDEPENDENT_VALIDATION_VIEWER_FREEZE_V1.json" (echo ERROR: freeze JSON missing& exit /b 1)

echo.
echo ============================================================
echo PASS: low-Hprior C validation viewer formally frozen pre-label.
echo DO NOT OPEN blind key or matching diagnostic.
echo NEXT: label all 58 pairs in index.html.
echo ============================================================
exit /b 0
