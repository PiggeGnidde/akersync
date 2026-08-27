@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

py -3 src\65_verify_akerminne_skane.py
if errorlevel 1 exit /b 1

echo.
echo AKERMINNE SKANE VERIFY: PASS
exit /b 0
