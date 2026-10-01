@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerAccess D0 - SJObO SMOKE TEST ONLY
echo ==============================================================================

py -3 analysis\akeraccess_v0a\skane_road_features_d0.py --municipality Sjöbo
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERACCESS D0 SJObO SMOKE: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERACCESS D0 SJObO SMOKE: FAIL
echo ==============================================================================
exit /b 1
