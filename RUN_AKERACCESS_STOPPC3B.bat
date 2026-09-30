@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerAccess - STOPPUNKT C3b - SPATIAL / AREA NEAR-TWINS
echo ==============================================================================

py -3 analysis\akeraccess_v0a\pea_neartwin_c3b.py
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERACCESS STOPPUNKT C3b: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERACCESS STOPPUNKT C3b: FAIL
echo ==============================================================================
exit /b 1
