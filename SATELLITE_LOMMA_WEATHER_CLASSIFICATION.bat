@echo off
setlocal
cd /d %~dp0
chcp 65001 >nul

echo ================================================================================
echo ÅkerSync · Satellite V1a · Lomma SMHI weather classification 2018-2026
echo ================================================================================

echo Säkerställer CA-certifikat för Python/SMHI ...
py -3 -c "import certifi" >nul 2>&1
if errorlevel 1 (
  echo certifi saknas - installerar ...
  py -3 -m pip install certifi
  if errorlevel 1 goto :fail
)
for /f "delims=" %%i in ('py -3 -c "import certifi; print(certifi.where())"') do set "SSL_CERT_FILE=%%i"
echo SSL_CERT_FILE=%SSL_CERT_FILE%

py -3 src\25b_satellite_lomma_weather_classification_robust.py --year-start 2018 --year-end 2026
if errorlevel 1 goto :fail

echo.
echo SATELLITE LOMMA WEATHER CLASSIFICATION: KLAR
pause
exit /b 0

:fail
echo.
echo SATELLITE LOMMA WEATHER CLASSIFICATION: FEL
pause
exit /b 1
