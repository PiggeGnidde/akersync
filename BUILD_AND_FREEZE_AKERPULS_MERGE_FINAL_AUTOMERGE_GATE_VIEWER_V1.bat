@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
cd /d "%~dp0"

set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "OUT=C:\AkerSyncRepo\work\akerpuls_merge_final_automerge_gate_viewer_v1"
set "FOUT=C:\AkerSyncRepo\work\akerpuls_merge_final_automerge_gate_viewer_freeze_v1"
set "CFREEZE=C:\AkerSyncRepo\work\akerpuls_merge_c_low_hprior_independent_validation_reveal_freeze_v1"

echo ============================================================
echo AKERPULS - FINAL BLIND MERGE-V1 AUTOMERGE GATE
echo Freeze C result + build/freeze 80-pair P95/Hprior^>P25 viewer
echo THIS IS THE FINAL BLIND TEST FOR CURRENT SIGNAL FAMILY
echo ============================================================

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo ERROR: wrong branch& exit /b 1)
for /f "delims=" %%S in ('git status --short') do (echo ERROR: working tree must be clean& git status --short& exit /b 1)
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD=%%H"
echo HEAD=%HEAD%

if exist "%OUT%" (echo ERROR: viewer output already exists: %OUT%& exit /b 1)
if exist "%FOUT%" (echo ERROR: viewer freeze output already exists: %FOUT%& exit /b 1)
if exist "%CFREEZE%" (echo ERROR: C reveal freeze output already exists unexpectedly: %CFREEZE%& exit /b 1)

echo.
echo [1/2] Final-gate contract tests
py -3 -m unittest tests.test_akerpuls_merge_final_automerge_gate_viewer_v1 -v
if errorlevel 1 exit /b 1

echo.
echo [2/2] Freeze C result, build 80 blind sheets, and freeze final gate pre-label
py -3 -u src\208_akerpuls_merge_final_automerge_gate_viewer_v1.py --output-dir "%OUT%" --freeze-output-dir "%FOUT%"
if errorlevel 1 exit /b 1

if not exist "%OUT%\index.html" (echo ERROR: final viewer missing& exit /b 1)
if not exist "%FOUT%\AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_VIEWER_FREEZE_V1.json" (echo ERROR: final viewer freeze missing& exit /b 1)

echo.
echo ============================================================
echo PASS: final 80-pair merge-v1 blind gate formally frozen.
echo DO NOT OPEN FINAL_AUTOMERGE_GATE_BLIND_KEY_DO_NOT_OPEN.csv.
echo STOP HERE and paste output before labeling.
echo ============================================================
exit /b 0
