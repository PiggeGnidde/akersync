@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerFro x AkerAccess D5 - ROAD-LOGISTICS BESTMATCH
echo ==============================================================================
echo Frozen C10 is read-only. D5 uses D4 road distance to Bjuv.
echo.

py -3 analysis\akeraccess_v0a\bestmatch_roadlogistics_d5.py
if errorlevel 1 goto :fail

echo.
echo Rebuilding local comparison map with D5 rankings...
py -3 analysis\akeraccess_v0a\akerfro_access_map_d3.py
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERFRO x AKERACCESS D5 + MAP: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERFRO x AKERACCESS D5 + MAP: FAIL
echo ==============================================================================
exit /b 1
