@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%CD%;%PYTHONPATH%"

echo ==============================================================================
echo AkerAccess D6b - VALIDATE PAVED PUBLIC-ROAD PROXIMITY
echo ==============================================================================
echo Reuses frozen D1 near-twin matches. No API calls.
echo.

py -3 analysis\akeraccess_v0a\validate_paved_public_d6b.py
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERACCESS D6b: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERACCESS D6b: FAIL
echo ==============================================================================
exit /b 1
