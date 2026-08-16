@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================================
echo ÅkerSync · Geometry × markanvändning · AIC/BIC modellselektion
echo ================================================================================
py -3 src\13_geometry_model_selection.py
if errorlevel 1 (
  echo.
  echo Modellselektionen misslyckades.
  exit /b 1
)
echo.
echo KLART.
pause
