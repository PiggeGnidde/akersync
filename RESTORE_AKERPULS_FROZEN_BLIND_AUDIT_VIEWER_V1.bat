@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"

echo ============================================================
echo AKERPULS - RESTORE FROZEN BLIND AUDIT VIEWER
echo RESTORE index.html + manifest ONLY
echo VERIFY AGAINST FORMAL PRE-LABEL FREEZE
echo ============================================================

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: expected branch %EXPECTED_BRANCH%, got %BRANCH%
  exit /b 1
)
for /f "delims=" %%S in ('git status --short') do (
  echo ERROR: working tree must be clean before restore.
  git status --short
  exit /b 1
)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

py -3 -u src\194_akerpuls_merge_restore_frozen_audit_viewer_v1.py
if errorlevel 1 exit /b 1

echo.
echo ============================================================
echo PASS: frozen viewer restored and hash-verified.
echo Open:
echo   C:\AkerSyncRepo\work\akerpuls_merge_blind_disagreement_audit_viewer_v1b\index.html
echo DO NOT open BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv.
echo ============================================================
exit /b 0
