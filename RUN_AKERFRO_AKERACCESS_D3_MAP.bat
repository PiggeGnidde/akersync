@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerFro x AkerAccess D3 - INTERACTIVE MAP
echo ==============================================================================
echo Builds local HTML and opens it in the default browser.
echo.

py -3 analysis\akeraccess_v0a\akerfro_access_map_d3.py
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERFRO x AKERACCESS D3 MAP: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERFRO x AKERACCESS D3 MAP: FAIL
echo ==============================================================================
exit /b 1
