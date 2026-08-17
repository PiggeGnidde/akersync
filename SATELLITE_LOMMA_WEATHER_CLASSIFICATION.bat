@echo off
setlocal
cd /d %~dp0
chcp 65001 >nul

echo ================================================================================
echo ÅkerSync · Satellite V1a · Lomma SMHI weather classification 2018-2026
echo ================================================================================

py -3 src\25_satellite_lomma_weather_classification.py --year-start 2018 --year-end 2026
if errorlevel 1 (
  echo.
  echo SATELLITE LOMMA WEATHER CLASSIFICATION: FEL
  pause
  exit /b 1
)

echo.
echo SATELLITE LOMMA WEATHER CLASSIFICATION: KLAR
pause
