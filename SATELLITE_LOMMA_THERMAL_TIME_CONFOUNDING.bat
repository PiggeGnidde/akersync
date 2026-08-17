@echo off
setlocal
cd /d %~dp0
chcp 65001 >nul

echo ================================================================================
echo ÅkerSync · Satellite V1a · Step 30 thermal-time/date confounding
echo ================================================================================
echo.
echo Lokal analys: inga nya Sentinel- eller SMHI-anrop.
echo Testar GDD5 + exakt datumposition mot T45/P45 med leave-one-year-out.
echo.

py -3 src\30_satellite_lomma_thermal_time_confounding.py --year-start 2018 --year-end 2026 --qa-thresholds 50,60,75,80 --primary-qa 50 --min-gdd-coverage 85
if errorlevel 1 goto :fail

echo.
echo SATELLITE LOMMA THERMAL TIME CONFOUNDING: KLAR
pause
exit /b 0

:fail
echo.
echo SATELLITE LOMMA THERMAL TIME CONFOUNDING: FEL
pause
exit /b 1
