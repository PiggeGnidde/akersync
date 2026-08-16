@echo off
setlocal
cd /d %~dp0

echo ==============================================================================
echo ÅkerSync · Satellite V1a · Lomma dense harvest-window analysis
echo ==============================================================================

py -3 src\21_satellite_lomma_harvest_window.py
if errorlevel 1 (
  echo.
  echo SATELLITE LOMMA HARVEST WINDOW: FEL
  pause
  exit /b 1
)

echo.
echo SATELLITE LOMMA HARVEST WINDOW: KLAR
pause
