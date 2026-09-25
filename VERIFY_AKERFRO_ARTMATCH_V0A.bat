@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerFro - Ertor - VERIFY FROZEN ARTMATCH v0a
echo ==============================================================================
py -3 analysis\akerfro_ertor_v0a\freeze_artmatch_v0a.py --mode verify
if errorlevel 1 goto :fail

echo.
echo VERIFY_AKERFRO_ARTMATCH_V0A: PASS
exit /b 0

:fail
echo.
echo ==============================================================================
echo VERIFY_AKERFRO_ARTMATCH_V0A: FAIL
echo ==============================================================================
exit /b 1
