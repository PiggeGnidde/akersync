@echo off
setlocal
cd /d %~dp0
chcp 65001 >nul

echo ================================================================================
echo ÅkerSync · Satellite V1a · Step 29 weather-window robustness
echo ================================================================================
echo.
echo Lokal analys: inga nya Sentinel/openEO-jobb.
echo Testar 14/30/45 dagar, P vs T vs P+T, vegetation control och LOYO år för år.
echo.

py -3 src\29_satellite_lomma_weather_window_robustness.py --year-start 2018 --year-end 2026 --qa-thresholds 50,60,75,80 --primary-qa 50
if errorlevel 1 goto :fail

echo.
echo SATELLITE LOMMA WEATHER WINDOW ROBUSTNESS: KLAR
pause
exit /b 0

:fail
echo.
echo SATELLITE LOMMA WEATHER WINDOW ROBUSTNESS: FEL
pause
exit /b 1
