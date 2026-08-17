@echo off
setlocal
cd /d %~dp0
chcp 65001 >nul

echo ================================================================================
echo ÅkerSync · Satellite V1a · Lomma TWI model decomposition 2018-2026
echo ================================================================================
echo.
echo Lokal analys only - inga nya Sentinel- eller SMHI-hamtningar.
echo Testar window, vegetation state och vader med leave-one-year-out.
echo QA-sensitivitet: 50, 60, 75, 80 procent.
echo.

py -3 src\28_satellite_lomma_twi_model_decomposition.py --year-start 2018 --year-end 2026 --qa-thresholds 50,60,75,80 --primary-qa 50
if errorlevel 1 goto :fail

echo.
echo SATELLITE LOMMA TWI MODEL DECOMPOSITION: KLAR
pause
exit /b 0

:fail
echo.
echo SATELLITE LOMMA TWI MODEL DECOMPOSITION: FEL
pause
exit /b 1
