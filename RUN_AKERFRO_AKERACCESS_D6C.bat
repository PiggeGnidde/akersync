@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%CD%;%PYTHONPATH%"

echo ==============================================================================
echo AkerFro x AkerAccess D6c - BESTMATCH WITH PAVED-ROAD VAGLOGISTIK
echo ==============================================================================
echo No API calls. Reuses D6b.
echo.

py -3 analysis\akeraccess_v0a\bestmatch_paved_road_d6c.py
if errorlevel 1 goto :fail

echo.
echo Rebuilding whole-Skane web preview with D6c...
CALL RUN_AKERFRO_ACCESS_WEB_V0B.bat
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERFRO x AKERACCESS D6c + WEB: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERFRO x AKERACCESS D6c + WEB: FAIL
echo ==============================================================================
exit /b 1
