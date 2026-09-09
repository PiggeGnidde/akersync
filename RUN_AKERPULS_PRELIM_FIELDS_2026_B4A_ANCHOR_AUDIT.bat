@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
set "EXPECTED_BRANCH=feature/akerpuls-prelim-fields-2026-v0a"
set "B4=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b4_diagnostic"
set "OUT=C:\AkerSyncRepo\work\akerpuls_prelim_fields_2026_v0_b4a_anchor_audit"
for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "%BRANCH%"=="%EXPECTED_BRANCH%" (echo FAIL: expected branch %EXPECTED_BRANCH%, got %BRANCH%.& exit /b 1)
py -3 -c "import numpy,pandas" >nul 2>nul || (echo FAIL: Python dependencies missing.& exit /b 1)
if not exist "%B4%\b4_summary.json" (echo FAIL: B4 summary missing.& exit /b 1)
echo ========================================================================================
echo AkerPuls 2026 - B4a REVIEWED ANCHOR AUDIT - ZERO PU
echo ========================================================================================
py -3 src\116_akerpuls_prelim_fields_2026_b4a_anchor_audit.py --b4-dir "%B4%" --output-dir "%OUT%"
exit /b %ERRORLEVEL%
