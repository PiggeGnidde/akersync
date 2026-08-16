@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================================================
echo ÅkerSync · Satellite V1a · Lomma NDVI visual QA map · 9 juli 2026
echo ==============================================================================
py -3 src\19_satellite_lomma_ndvi_map.py --date 2026-07-09
if errorlevel 1 goto :fail
start "" data\derived\satellite_poc\lomma_ndvi_20260709_map.html
pause
exit /b 0
:fail
echo.
echo SATELLITE LOMMA NDVI MAP: FEL
pause
exit /b 1
