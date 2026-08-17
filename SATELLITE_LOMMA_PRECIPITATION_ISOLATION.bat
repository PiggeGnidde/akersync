@echo off
setlocal
cd /d %~dp0
chcp 65001 >nul

echo ================================================================================
echo ÅkerSync · Satellite V1a · Step 31 precipitation isolation
 echo ================================================================================
echo.
echo Lokal analys: ingen ny Sentinel- eller SMHI-hamtning.
echo Testar precipitation/temperature 14, 30 och 45 dagar efter GDD+datumkontroll.
echo.

py -3 src\31_satellite_lomma_precipitation_isolation.py --year-start 2018 --year-end 2026 --qa-thresholds 50,60,75,80 --primary-qa 50 --min-gdd-coverage 85
if errorlevel 1 goto :fail

echo.
echo SATELLITE LOMMA PRECIPITATION ISOLATION: KLAR
pause
exit /b 0

:fail
echo.
echo SATELLITE LOMMA PRECIPITATION ISOLATION: FEL
pause
exit /b 1
