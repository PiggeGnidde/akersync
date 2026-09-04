@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
echo OFFLINE PIXEL EXPORT - existing images only - no model changes
echo [1/2] Regression tests...
py -3 -m unittest tests.test_rapskartan_parity_diagnostic tests.test_rapskartan_pixel_cases -q >nul
if errorlevel 1 exit /b 1
echo [2/2] Exporting up to five pixel cases. No AWS credentials needed.
py -3 -u src\103_export_rapskartan_pixel_cases.py %*
exit /b %ERRORLEVEL%
