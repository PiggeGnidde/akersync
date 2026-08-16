@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================================================
echo ÅkerSync · Satellite V1a · Copernicus openEO auth test
echo ==============================================================================
py -3 -c "import openeo" >nul 2>&1
if errorlevel 1 (
  echo Installerar Python-paketet openeo ...
  py -3 -m pip install openeo
  if errorlevel 1 goto :fail
)
py -3 src\17_satellite_auth_test.py
if errorlevel 1 goto :fail
pause
exit /b 0
:fail
echo.
echo SATELLITE AUTH: FEL
pause
exit /b 1
