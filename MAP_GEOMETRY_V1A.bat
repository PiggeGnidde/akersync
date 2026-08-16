@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================================================
echo ÅkerSync · Geometry V1a · visuell kandidatkarta
echo ==============================================================================
py -3 src\09_map_geometry_v1a.py
if errorlevel 1 (
  echo.
  echo Geometry-kartan misslyckades.
  exit /b 1
)
echo.
echo KLART: dist\geometry_v1a_candidates_map.html
echo.
start "" dist\geometry_v1a_candidates_map.html
