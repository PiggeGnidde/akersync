@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "LABELS=%USERPROFILE%\Downloads\merge_final_automerge_gate_labels.csv"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_final_automerge_gate_labels_freeze_v1"

echo ============================================================
echo AKERPULS - FREEZE FINAL AUTOMERGE GATE LABELS
echo NO BLIND-KEY REVEAL BEFORE THIS PASSES
echo ============================================================
echo LABELS=%LABELS%

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo ERROR: wrong branch& exit /b 1)
for /f "delims=" %%S in ('git status --short') do (echo ERROR: working tree must be clean& git status --short& exit /b 1)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if not exist "%LABELS%" (echo ERROR: exported labels not found: %LABELS%& exit /b 1)
if exist "%OUT%" (echo ERROR: output already exists: %OUT%& exit /b 1)

echo.
echo [1/2] Label-freeze contract tests
py -3 -m unittest tests.test_akerpuls_merge_final_automerge_gate_labels_freeze_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Validate and freeze all 80 final blind labels
py -3 -u src\209_akerpuls_merge_final_automerge_gate_labels_freeze_v1.py --labels "%LABELS%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_LABELS_FREEZE_V1.json" (echo ERROR: freeze JSON missing& exit /b 1)

echo.
echo ============================================================
echo PASS: final 80 blind labels formally frozen.
echo Blind key remains unrevealed.
echo STOP HERE and paste output before final reveal/pass-fail.
echo ============================================================
exit /b 0
