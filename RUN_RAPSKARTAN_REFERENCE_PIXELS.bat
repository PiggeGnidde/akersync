@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
echo [1/2] Reference request safety tests - no network...
py -3 -m unittest tests.test_rapskartan_pixel_reference tests.test_rapskartan_parity_diagnostic -q >nul
if errorlevel 1 exit /b 1
echo [2/2] At most ten data requests total, plus OAuth login. No automatic retries.
echo Uses CDSE_CLIENT_ID and CDSE_CLIENT_SECRET. Never upload these credentials.
py -3 -u src\104_fetch_rapskartan_reference_pixels.py %*
exit /b %ERRORLEVEL%
