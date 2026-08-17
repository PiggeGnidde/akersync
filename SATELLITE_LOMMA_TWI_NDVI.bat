@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================================================
echo ÅkerSync · Satellite V1a · Lomma TWI vs NDVI inom skifte
echo ==============================================================================
py -3 src\22_satellite_lomma_twi_ndvi.py --start 2026-04-01 --end 2026-07-14 --edge-buffer-m 10 --min-pixels 20 --min-coverage 70 --min-persistence-dates 4
if errorlevel 1 goto :fail
echo.
echo SATELLITE LOMMA TWI NDVI: KLAR
pause
exit /b 0
:fail
echo.
echo SATELLITE LOMMA TWI NDVI: FEL
pause
exit /b 1
