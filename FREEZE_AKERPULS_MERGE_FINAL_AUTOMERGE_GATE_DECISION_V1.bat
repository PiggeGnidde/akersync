@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"
set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_final_automerge_gate_decision_freeze_v1"

echo ============================================================
echo AKERPULS - FREEZE FINAL MERGE-V1 AUTOMERGE GATE DECISION
echo No blind-key reveal required
echo ============================================================
for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo ERROR: wrong branch& exit /b 1)
for /f "delims=" %%S in ('git status --short') do (echo ERROR: working tree must be clean& git status --short& exit /b 1)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%
if exist "%OUT%" (echo ERROR: output already exists: %OUT%& exit /b 1)
echo.
echo [1/2] Decision-freeze contract tests
py -3 -m unittest tests.test_akerpuls_merge_final_automerge_gate_decision_freeze_v1 -v
if errorlevel 1 exit /b 1
echo.
echo [2/2] Apply prospectively frozen final gate and freeze decision
py -3 -u src\210_akerpuls_merge_final_automerge_gate_decision_freeze_v1.py
if errorlevel 1 exit /b 1
echo.
echo ============================================================
echo PASS: final merge-v1 gate decision formally frozen.
echo STOP HERE and paste output before proposal-only geometry policy.
echo ============================================================
exit /b 0
