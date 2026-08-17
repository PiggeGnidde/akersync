@echo off
setlocal
cd /d %~dp0
chcp 65001 >nul

echo ================================================================================
echo ÅkerSync · Satellite V1a · Historical TWI experiment

echo dry / middle / wet years from SMHI classification

echo ================================================================================

py -3 src\26_satellite_lomma_historical_twi_experiment.py
if errorlevel 1 goto :fail

echo.
echo SATELLITE LOMMA HISTORICAL TWI EXPERIMENT: KLAR
pause
exit /b 0

:fail
echo.
echo SATELLITE LOMMA HISTORICAL TWI EXPERIMENT: FEL
pause
exit /b 1
