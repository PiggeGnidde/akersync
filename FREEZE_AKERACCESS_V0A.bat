@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%CD%;%PYTHONPATH%"

echo ==============================================================================
echo AkerAccess v0a - FORMAL FREEZE
echo ==============================================================================
echo Builds the generic product table from frozen D0, validates D1, hashes artifacts.
echo No API calls.
echo.

py -3 analysis\akeraccess_v0a\build_akeraccess_product_v0a.py
if errorlevel 1 goto :fail

py -3 analysis\akeraccess_v0a\freeze_akeraccess_v0a.py
if errorlevel 1 goto :fail

CALL VERIFY_AKERACCESS_V0A_FREEZE.bat
exit /b %ERRORLEVEL%

:fail
echo.
echo ==============================================================================
echo AKERACCESS v0a FREEZE: FAIL
echo ==============================================================================
exit /b 1
