@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "LABELS=%USERPROFILE%\Downloads\merge_ab_independent_validation_labels.csv"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_ab_independent_blind_validation_labels_freeze_v1"

echo ============================================================
echo AKERPULS - FREEZE INDEPENDENT BLIND A/B VALIDATION LABELS
echo NO A/B REVEAL BEFORE THIS FREEZE PASSES
echo ============================================================
echo LABELS=%LABELS%

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo ERROR: wrong branch& exit /b 1)
for /f "delims=" %%S in ('git status --short') do (echo ERROR: working tree must be clean& git status --short& exit /b 1)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if not exist "%LABELS%" (echo ERROR: exported labels not found: %LABELS%& exit /b 1)
if exist "%OUT%" (echo ERROR: label-freeze output already exists: %OUT%& exit /b 1)

echo.
echo [1/2] Label-freeze contract tests
py -3 -m unittest tests.test_akerpuls_merge_ab_independent_blind_validation_labels_freeze_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Validate and freeze 100 blind A/B validation labels without reveal
py -3 -u src\201_akerpuls_merge_ab_independent_blind_validation_labels_freeze_v1.py --labels "%LABELS%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_LABELS_FREEZE_V1.json" (echo ERROR: freeze JSON missing& exit /b 1)

echo.
echo ============================================================
echo PASS: all 100 independent blind A/B labels formally frozen.
echo BLIND KEY HAS NOT BEEN REVEALED.
echo STOP HERE and paste output before any reveal/analysis.
echo ============================================================
exit /b 0
