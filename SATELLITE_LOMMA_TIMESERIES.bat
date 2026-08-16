@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================================================
echo ÅkerSync · Satellite V1a · Lomma NDVI tidsserie · 1 apr - 16 aug 2026
echo ==============================================================================
py -3 src\20_satellite_lomma_timeseries.py --start 2026-04-01 --end 2026-08-16 --cadence-days 14 --anchor-date 2026-07-09
if errorlevel 1 goto :fail
echo.
echo SATELLITE LOMMA TIMESERIES: KLAR
pause
exit /b 0
:fail
echo.
echo SATELLITE LOMMA TIMESERIES: FEL
pause
exit /b 1
