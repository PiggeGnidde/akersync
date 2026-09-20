@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "LABELS=%USERPROFILE%\Downloads\merge_disagreement_audit_labels.csv"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_labels_freeze_v1"

echo ============================================================
echo AKERPULS - FREEZE COMPLETED BLIND MERGE AUDIT LABELS
echo BEFORE ANY BLIND-KEY REVEAL
echo ============================================================
echo LABELS=%LABELS%
echo OUTPUT=%OUT%
echo.

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before label freeze.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if not exist "%LABELS%" (
  echo ERROR: exported labels file not found:
  echo   %LABELS%
  echo If Chrome renamed it, move/rename the completed export to that exact filename.
  exit /b 1
)
if exist "%OUT%" (
  echo ERROR: label-freeze output already exists: %OUT%
  echo Do not overwrite a freeze.
  exit /b 1
)

echo.
echo [1/2] Label-freeze contract tests
py -3 -m unittest tests.test_akerpuls_merge_blind_labels_freeze_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Validate and freeze 100 blind labels without reveal
py -3 -u src\193_akerpuls_merge_blind_labels_freeze_v1.py --labels "%LABELS%" --output-dir "%OUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\merge_disagreement_audit_labels_frozen.csv" (echo ERROR: frozen labels missing& exit /b 1)
if not exist "%OUT%\AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_LABELS_FREEZE_V1.json" (echo ERROR: label freeze JSON missing& exit /b 1)

for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: repository changed during label freeze.
  git status --short
  exit /b 1
)

echo.
echo ============================================================
echo PASS: all 100 blind human labels formally frozen.
echo BLIND KEY HAS NOT BEEN REVEALED.
echo STOP HERE and paste output before any reveal/analysis.
echo ============================================================
exit /b 0
