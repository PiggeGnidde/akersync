@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 src\map_water_regimes.py
if errorlevel 1 (
  echo.
  echo MAP_WATER_REGIMES MISSLYCKADES.
  pause
  exit /b 1
)
echo.
echo Öppnar kartan i webbläsaren...
start "" "dist\water_regimes_skane.html"
pause
