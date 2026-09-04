@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
echo Rapskartan parity diagnostic - OFFLINE ONLY - no full map generation
echo No AWS credentials needed. Existing scene assets will not be modified.
echo [1/2] Diagnostic regression tests...
py -3 -m unittest tests.test_rapskartan_map_product tests.test_rapskartan_parity_diagnostic -v
if errorlevel 1 exit /b 1
echo [2/2] Reference replay and checkpointed local diagnostics...
py -3 -u src\102_diagnose_rapskartan_2025_parity.py %*
exit /b %ERRORLEVEL%
