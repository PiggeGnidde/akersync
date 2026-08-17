@echo off
setlocal
cd /d %~dp0
chcp 65001 >nul

echo ================================================================================
echo ÅkerSync · Satellite V1a · Lomma all-year TWI x weather 2018-2026
echo ================================================================================
echo.
echo Detta kan ta tid: upp till 36 accepterade år-fönster och fallback-datum vid moln.
echo Befintliga NDVI-TIFF:ar återanvänds automatiskt.
echo.

py -3 src\27b_satellite_lomma_multiyear_twi_weather_robust.py --year-start 2018 --year-end 2026 --max-candidates 5 --min-usable-field-share 50 --min-field-coverage 70
if errorlevel 1 goto :fail

echo.
echo SATELLITE LOMMA MULTIYEAR TWI WEATHER: KLAR
pause
exit /b 0

:fail
echo.
echo SATELLITE LOMMA MULTIYEAR TWI WEATHER: FEL
pause
exit /b 1
