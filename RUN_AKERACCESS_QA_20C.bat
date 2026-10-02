@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%CD%;%PYTHONPATH%"

echo ==============================================================================
echo AkerAccess exact QA - field 62263103013^|20C
echo ==============================================================================
echo Reuses cached D0 + NVDB Slitlager/Vaghallare. No API calls.
echo Distinguishes selected OSM entry from nearest paved public-road evidence.
echo.

py -3 analysis\akeraccess_v0a\surface_public_road_d6a.py --field-id "62263103013|20C"
if errorlevel 1 goto :fail

echo.
echo ==============================================================================
echo EXACT FIELD QA 20C: PASS
echo ==============================================================================
exit /b 0

:fail
echo.
echo ==============================================================================
echo EXACT FIELD QA 20C: FAIL
echo ==============================================================================
exit /b 1
