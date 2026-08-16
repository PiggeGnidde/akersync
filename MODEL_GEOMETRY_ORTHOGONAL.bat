@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================================================
echo ÅkerSync · Geometry × markanvändning · orthogonal-ish model selection
echo ==============================================================================
py -3 src\14_geometry_orthogonal_model_selection.py
if errorlevel 1 (
  echo.
  echo Orthogonal geometry-model analysis FAILED.
  exit /b 1
)
echo.
echo KLART.
pause
