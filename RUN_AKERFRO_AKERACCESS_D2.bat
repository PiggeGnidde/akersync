@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerFro x AkerAccess D2 - BESTMATCH JOIN + INCREMENTAL LIFT
echo ==============================================================================
echo Frozen AkerFro/C10 and D0 are read-only. No API calls.
echo.

py -3 analysis\akeraccess_v0a\akerfro_access_bestmatch_d2.py
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERFRO x AKERACCESS D2: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERFRO x AKERACCESS D2: FAIL
echo ==============================================================================
exit /b 1
