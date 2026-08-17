@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ====================================================================================================
echo ÅkerSync · Satellite V1a · Lomma TWI quintile response curve + bootstrap
 echo ====================================================================================================

py -3 src\23_satellite_lomma_twi_response_curve.py
if errorlevel 1 goto :fail

echo.
echo SATELLITE LOMMA TWI RESPONSE CURVE: KLAR
pause
exit /b 0

:fail
echo.
echo SATELLITE LOMMA TWI RESPONSE CURVE: FEL
pause
exit /b 1
