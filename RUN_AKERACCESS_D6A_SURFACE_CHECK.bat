@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%CD%;%PYTHONPATH%"

echo ==============================================================================
echo AkerAccess D6a - NVDB SLITLAGER + EXACT FIELD CHECK
echo ==============================================================================
echo Fetches Slitlager once for Skane, computes paved public-road distance,
echo and prints the exact NVDB values for field 62263103013^|20A.
echo API key is read from .env and never printed.
echo.

py -3 analysis\akeraccess_v0a\surface_public_road_d6a.py
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERACCESS D6a: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERACCESS D6a: FAIL
echo ==============================================================================
exit /b 1
