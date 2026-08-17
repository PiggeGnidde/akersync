@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ================================================================================
echo ÅkerSync · Satellite V1a · Lomma multiyear Sentinel-2 preflight · 2018-2026
echo ================================================================================

py -3 src\24_satellite_lomma_multiyear_preflight.py --year-start 2018 --year-end 2026
if errorlevel 1 goto :fail

echo.
echo SATELLITE LOMMA MULTIYEAR PREFLIGHT: KLAR
pause
exit /b 0

:fail
echo.
echo SATELLITE LOMMA MULTIYEAR PREFLIGHT: FEL
pause
exit /b 1
