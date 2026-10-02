@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%CD%;%PYTHONPATH%"
echo ==============================================================================
echo AkerFro x AkerAccess WEB v0b - WHOLE-SKANE SCREENING
echo ==============================================================================
echo Auto-discovers existing real AkerFro web dist and builds a separate preview.
echo Existing web dist is never modified.
echo.
py -3 src\92_build_akerfro_access_web_v0b.py
if errorlevel 1 goto :fail
py -3 src\93_verify_akerfro_access_web_v0b.py
if errorlevel 1 goto :fail
echo.
echo ==============================================================================
echo AKERFRO x AKERACCESS WEB v0b: PASS
echo Preview: dist_akerfro_access_v0b
echo Start with START_AKERFRO_ACCESS_WEB_V0B.bat
echo ==============================================================================
exit /b 0
:fail
echo.
echo ==============================================================================
echo AKERFRO x AKERACCESS WEB v0b: FAIL
echo ==============================================================================
exit /b 1
