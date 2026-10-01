@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerAccess D0 - SKANE ROAD FEATURE BUILD
echo ==============================================================================
echo This run is resumable. OSM is cached per municipality and NVDB once for Skane.
echo API credential is read locally from .env and is never printed.
echo.

py -3 analysis\akeraccess_v0a\skane_road_features_d0.py
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERACCESS D0 SKANE: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERACCESS D0 SKANE: FAIL
echo Re-run the same BAT after a fix; completed municipality caches are reused.
echo ==============================================================================
exit /b 1
