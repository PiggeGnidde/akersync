@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%CD%;%PYTHONPATH%"

echo ==============================================================================
echo AkerFro x AkerAccess BestMatch v0b - FORMAL FREEZE
echo ==============================================================================
echo Freezes selected balanced policy on frozen C10 + frozen AkerAccess v0a.
echo No API calls.
echo.

py -3 analysis\akeraccess_v0a\build_bestmatch_v0b_product.py
if errorlevel 1 goto :fail

py -3 analysis\akeraccess_v0a\freeze_bestmatch_v0b.py
if errorlevel 1 goto :fail

CALL VERIFY_AKERFRO_AKERACCESS_BESTMATCH_V0B_FREEZE.bat
exit /b %ERRORLEVEL%

:fail
echo.
echo ==============================================================================
echo BESTMATCH v0b FREEZE: FAIL
echo ==============================================================================
exit /b 1
