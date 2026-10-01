@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerAccess D4 - ROAD DISTANCE TO BJUV
echo ==============================================================================
echo Downloads/caches a 4x4 OSM route network once, then routes all fields locally.
echo No per-field routing API calls.
echo.

py -3 analysis\akeraccess_v0a\bjuv_route_distance_d4.py
if errorlevel 1 goto :fail

echo.
echo Rebuilding D3 map with D4 road distances...
py -3 analysis\akeraccess_v0a\akerfro_access_map_d3.py
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERACCESS D4 + D3 MAP: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERACCESS D4 + D3 MAP: FAIL
echo ==============================================================================
exit /b 1
