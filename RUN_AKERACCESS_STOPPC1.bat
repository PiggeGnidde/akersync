@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo AkerAccess - STOPPUNKT C1 - OSM LAST-MILE PATH PROFILE
echo ==============================================================================

echo.
echo [1/2] Unit tests...
py -3 -m unittest tests.test_akeraccess_path_profile_core -v
if errorlevel 1 goto :fail

echo.
echo [2/2] Profile last-mile paths...
py -3 analysis\akeraccess_v0a\path_profile_c1.py
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo AKERACCESS STOPPUNKT C1: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo AKERACCESS STOPPUNKT C1: FAIL
echo ==============================================================================
exit /b 1
