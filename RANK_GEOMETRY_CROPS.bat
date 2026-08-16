@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================================================
echo ÅkerSync · Geometry x grodkod · size-matched ranking
echo ==============================================================================
py -3 src\11_geometry_crop_contrast.py
if errorlevel 1 (
  echo.
  echo Geometry x grodkod misslyckades.
  exit /b 1
)
echo.
echo KLART.
pause
